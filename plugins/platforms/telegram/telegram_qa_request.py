"""Endpoint-specific raw acceptance before PTB loses receipt field types."""
from gateway.platforms.base import SendResult
from .telegram_ids import normalize_telegram_chat_id


class TelegramDeliveryUncertain(Exception):
    """The request may have committed; no retry or formatting fallback is safe."""


def raise_if_delivery_uncertain(error):
    """Do not let an unconfirmed submission enter retry/fallback classifiers."""
    if isinstance(error, TelegramDeliveryUncertain):
        raise error


class TelegramQARequestMixin:
    async def _qa_await_delivery(self, awaitable, *, scope_chat_id, metadata=None, **deadline):
        """Keep the outer wall-clock deadline inside the QA uncertainty fence."""
        from .adapter import _await_with_thread_deadline
        try:
            return await _await_with_thread_deadline(awaitable, **deadline)
        except TimeoutError as error:
            # The bounded task may already have submitted or even committed.
            # An outer expiry cannot establish non-submission like a connect error.
            if self._qa_enabled(str(scope_chat_id), metadata):
                raise TelegramDeliveryUncertain("Telegram delivery deadline expired") from error
            raise

    @staticmethod
    def _qa_merge_object_defaults(value, defaults):
        """Preserve explicit None/False while merging SDK default sentinels."""
        from inspect import signature
        parameters = signature(type(value)).parameters
        fields = {name: getattr(value, name) for name in parameters if hasattr(value, name)}
        for name, current in fields.items():
            if current is parameters[name].default and name in defaults:
                fields[name] = defaults[name]
        return type(value)(**fields)

    def _qa_native_defaults(self, endpoint, kwargs):
        # do_api_request intentionally omits ExtBot's convenience defaults. Only
        # calls replacing native message methods inherit them; raw rich calls do not.
        from telegram import LinkPreviewOptions, ReplyParameters
        defaults = getattr(self._bot, 'defaults', None)
        if defaults is None or endpoint not in {'sendMessage', 'editMessageText'}:
            return
        fields = ['parse_mode', 'link_preview_options']
        if endpoint == 'sendMessage':
            fields += ['disable_notification', 'protect_content']
        for field in fields:
            if field in defaults.api_defaults:
                kwargs.setdefault(field, defaults.api_defaults[field])
        preview = kwargs.get('link_preview_options')
        if isinstance(preview, LinkPreviewOptions) and defaults.link_preview_options is not None:
            kwargs['link_preview_options'] = self._qa_merge_object_defaults(preview,
                {name: getattr(defaults.link_preview_options, name) for name in LinkPreviewOptions.__slots__})
        reply = kwargs.get('reply_parameters')
        if isinstance(reply, ReplyParameters):
            kwargs['reply_parameters'] = self._qa_merge_object_defaults(reply, {
                'allow_sending_without_reply': defaults.allow_sending_without_reply,
                'quote_parse_mode': defaults.quote_parse_mode,
            })

    async def _qa_delivery_request(self, scope_chat_id: str, endpoint: str, *, metadata=None, **kwargs):
        """Invoke and confirm one QA mutation before SDK DTO coercion loses evidence.

        Native non-QA calls retain their convenience API. QA uses the same public
        SDK transport, but binds its raw receipt to the actual outgoing target.
        No exception text or stale context can establish non-submission.
        """
        if not self._qa_enabled(scope_chat_id, metadata):
            if "api_kwargs" in kwargs or endpoint == "sendRichMessage":
                return await self._bot.do_api_request(endpoint, **kwargs)
            native = {"sendMessage": "send_message", "editMessageText": "edit_message_text",
                      "editMessageReplyMarkup": "edit_message_reply_markup",
                      "answerCallbackQuery": "answer_callback_query"}[endpoint]
            return await getattr(self._bot, native)(**kwargs)

        from telegram.error import (
            BadRequest, ChatMigrated, Conflict, EndPointNotFound, Forbidden,
            InvalidToken, RetryAfter,
        )
        import httpx

        timeouts = self._qa_request_parameters(endpoint, kwargs)
        # Missing raw support is a local pre-submit capability failure, never a
        # silent downgrade to a lossy Message receipt.
        if not callable(getattr(self._bot, "do_api_request", None)):
            raise ValueError("Telegram QA requires public raw SDK request support")
        try:
            result = await self._bot.do_api_request(endpoint, api_kwargs=kwargs, return_type=None, **timeouts)
        except Exception as error:
            # PTB wraps InvalidToken for initialized raw calls. A documented
            # endpoint is not an unknown-rich capability, regardless of status.
            if (endpoint != "sendRichMessage" and isinstance(error, EndPointNotFound)
                    and isinstance(error.__cause__, InvalidToken)):
                raise error.__cause__ from None
            if isinstance(error, (BadRequest, ChatMigrated, Conflict, EndPointNotFound,
                                  Forbidden, InvalidToken, RetryAfter)):
                raise
            cause = error
            seen = set()
            while cause is not None and id(cause) not in seen:
                seen.add(id(cause))
                if isinstance(cause, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
                    raise
                cause = cause.__cause__
            raise TelegramDeliveryUncertain(str(error)) from error

        return self._qa_validate_receipt(endpoint, kwargs, result)

    def _qa_request_parameters(self, endpoint, kwargs):
        from telegram import LinkPreviewOptions, ReplyParameters

        # Normalize only convenience parameters used by these native call sites.
        # Preserve omitted timeout sentinels, explicit False and SDK objects.
        timeouts = {key: kwargs.pop(key) for key in
                    ("read_timeout", "write_timeout", "connect_timeout", "pool_timeout") if key in kwargs}
        extra = kwargs.pop("api_kwargs", None)
        reply_to = kwargs.pop("reply_to_message_id", None)
        allow_reply_supplied = "allow_sending_without_reply" in kwargs
        allow_reply = kwargs.pop("allow_sending_without_reply", None)
        if kwargs.get("reply_parameters") is not None and (reply_to is not None or allow_reply_supplied):
            raise ValueError("Reply convenience arguments and reply_parameters are mutually exclusive")
        if reply_to is not None:
            reply_args = {"allow_sending_without_reply": allow_reply} if allow_reply is not None else {}
            kwargs["reply_parameters"] = ReplyParameters(message_id=reply_to, **reply_args)
        disable_preview = kwargs.pop("disable_web_page_preview", None)
        if disable_preview and kwargs.get("link_preview_options"):
            raise ValueError("Preview convenience arguments and link_preview_options are mutually exclusive")
        if disable_preview is not None:
            kwargs["link_preview_options"] = LinkPreviewOptions(is_disabled=disable_preview)
        if extra is None:
            self._qa_native_defaults(endpoint, kwargs)
        if extra:
            kwargs.update(extra)
        if endpoint in {"sendMessage", "editMessageText"}:
            kwargs.setdefault("parse_mode", None)
        if "chat_id" in kwargs:
            kwargs["chat_id"] = normalize_telegram_chat_id(kwargs["chat_id"])
        return timeouts

    @staticmethod
    def _qa_validate_receipt(endpoint, kwargs, result):
        if endpoint == "answerCallbackQuery" or (
            endpoint in {"editMessageText", "editMessageReplyMarkup"}
            and kwargs.get("inline_message_id") is not None
            and kwargs.get("chat_id") is None and kwargs.get("message_id") is None
        ):
            if result is not True:
                raise TelegramDeliveryUncertain("Telegram boolean endpoint did not confirm success")
            return result
        if not isinstance(result, dict):
            raise TelegramDeliveryUncertain("Telegram message endpoint returned no raw message")
        chat = result.get("chat")
        message_id = result.get("message_id")
        valid = (type(message_id) is int and message_id > 0 and isinstance(chat, dict)
                 and type(chat.get("id")) is int and chat["id"] != 0
                 and type(result.get("date")) is int)
        target = kwargs.get("chat_id")
        if type(target) is int:
            valid = valid and chat.get("id") == target if isinstance(chat, dict) else False
        elif isinstance(target, str) and target.startswith("@"):
            username = chat.get("username") if isinstance(chat, dict) else None
            valid = valid and isinstance(username, str) and username.casefold() == target[1:].casefold()
        else:
            valid = False
        if endpoint in {"editMessageText", "editMessageReplyMarkup"}:
            valid = valid and type(kwargs.get("message_id")) is int and message_id == kwargs["message_id"]
        if not valid:
            raise TelegramDeliveryUncertain("Telegram raw message receipt does not confirm the requested target")
        return result

    async def _qa_message_request(self, endpoint, **kwargs):
        chat_id = str(kwargs.get("chat_id"))
        if not self._qa_enabled(chat_id):
            native = {"sendMessage": "send_message", "editMessageText": "edit_message_text"}[endpoint]
            return await getattr(self._bot, native)(**kwargs)
        raw = await self._qa_delivery_request(chat_id, endpoint, **kwargs)
        try:
            from telegram import Message
            return Message.de_json(raw, self._bot)
        except Exception as error:
            # A target-bound raw receipt is still post-submit evidence when the
            # SDK rejects another DTO field. Never reopen the retry classifier.
            raise TelegramDeliveryUncertain("Telegram message receipt could not be decoded") from error

    @staticmethod
    def _qa_uncertain_result(error):
        # Do not classify exception text: it can contain misleading retry markers.
        return SendResult(success=False, error="Telegram delivery outcome unknown",
                          retryable=False, delivery_uncertain=True,
                          raw_response={"delivery_uncertain": True})

    @staticmethod
    def _qa_can_fallback(chat_id, error, metadata=None):
        return not isinstance(error, TelegramDeliveryUncertain)
