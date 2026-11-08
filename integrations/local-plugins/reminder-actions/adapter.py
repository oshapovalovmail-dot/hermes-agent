"""Owner-bound reminder controls over the bundled Telegram transport."""
import asyncio
from contextlib import suppress
import logging
from pathlib import Path
import re
import sys

from . import watch_buttons as controls
from .watch_state import Store
from gateway.platforms.base import MessageEvent, SendResult, merge_pending_message_event
from gateway.session import build_session_key
from hermes_cli.config import get_hermes_home
from plugins.platforms.telegram import adapter as native
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ApplicationHandlerStop

logger = logging.getLogger(__name__)



class ReminderAdapter(native.TelegramAdapter):
    def __init__(self, config, *, root, route, jobs):
        super().__init__(config)
        self.reminder_root = Path(root)
        self.reminder_route = dict(route)
        self.reminder_jobs = frozenset(jobs)
        self._reminder_send_lock = asyncio.Lock()
        self._reminder_home = Path(get_hermes_home()).resolve()

    def _store(self, function, *args, **kwargs):
        store = Store(self.reminder_root, jobs=self.reminder_jobs)
        try:
            return function(store, *args, **kwargs)
        finally:
            store.db.close()

    async def _db(self, function, *args, **kwargs):
        return await asyncio.to_thread(self._store, function, *args, **kwargs)

    async def connect(self, **kwargs):
        if await asyncio.to_thread(Path(get_hermes_home()).resolve) != self._reminder_home:
            return False
        connected = await super().connect(**kwargs)
        if connected:
            def enable(store):
                with store.db:
                    store.put('buttons_enabled', self.reminder_route)
            await self._db(enable)
        return connected

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        if await asyncio.to_thread(Path(get_hermes_home()).resolve) != self._reminder_home:
            return SendResult(success=False, error='reminder_profile_mismatch')
        metadata = metadata or {}
        job = metadata.get('job_id')
        if job not in self.reminder_jobs or not controls.MARKER.search(content):
            return await super().send(chat_id, content, reply_to=reply_to, metadata=metadata)
        async with self._reminder_send_lock:
            try:
                delivery = await self._db(controls.lookup, content, job, chat_id, metadata.get('thread_id'))
                if not delivery['cards']:
                    # Acknowledge cancellation, not a fabricated Telegram message receipt.
                    return SendResult(success=True, raw_response={'suppressed': 'owner_closed',
                                                                  'delivery_id': delivery['id']})
                receipts = []
                for card in delivery['cards']:
                    ids = card['message_ids']
                    if card['send_state'] == 'ready':
                        await self._db(controls.send_state, card['token'], 'sending')
                        result = await super().send(chat_id, card['text'], reply_to=reply_to, metadata=metadata)
                        if not result.success:
                            raw = result.raw_response if isinstance(result.raw_response, dict) else {}
                            if (result.error in ('send_path_degraded', 'Not connected')
                                    and not result.message_id and not result.continuation_message_ids
                                    and not raw.get('message_ids')):
                                await self._db(controls.send_state, card['token'], 'ready')
                            return result
                        raw = result.raw_response if isinstance(result.raw_response, dict) else {}
                        ids = raw.get('message_ids') or ([result.message_id] if result.message_id else [])
                        await self._db(controls.mark_sent, card['token'], ids, self._bot.id)
                    elif card['send_state'] != 'sent':
                        return SendResult(success=False, error='reminder_delivery_uncertain_no_automatic_resend')
                    markup = InlineKeyboardMarkup([[InlineKeyboardButton(**button) for button in row]
                                                   for row in card['buttons']])
                    try:
                        await self._bot.edit_message_reply_markup(chat_id=chat_id, message_id=int(ids[-1]),
                                                                 reply_markup=markup)
                    except Exception as exc:
                        # Telegram rejects an identical keyboard on a replay; that is already applied.
                        if 'message is not modified' not in str(exc).lower():
                            raise
                    receipts.extend(str(mid) for mid in ids)
                return SendResult(success=True, message_id=receipts[0],
                                  raw_response={'message_ids': receipts, 'reminder_controls': True,
                                                'delivery_id': delivery['id']})
            except Exception as exc:
                logger.warning('Reminder controls delivery failed: %s', type(exc).__name__)
                return SendResult(success=False, error='reminder_controls_' + type(exc).__name__)

    def _admit_draft(self, event):
        """Queue a new authenticated turn, never an approval/clarify answer or mid-turn injection."""
        if self._message_handler is None or Path(get_hermes_home()).resolve() != self._reminder_home:
            return False
        key = build_session_key(event.source,
                                group_sessions_per_user=self.config.extra.get('group_sessions_per_user', True),
                                thread_sessions_per_user=self.config.extra.get('thread_sessions_per_user', False))
        if key in self._active_sessions:
            self._heal_stale_session_lock(key)
        if key in self._active_sessions:
            merge_pending_message_event(self._pending_messages, key, event, merge_text=True)
            return True
        return bool(self._start_session_processing(event, key))

    async def _handle_callback_query(self, update, context):
        query = update.callback_query
        if query is None or not (query.data or '').startswith('wr:'):
            return await super()._handle_callback_query(update, context)
        await self.reminder_callback(update, context)

    async def reminder_callback(self, update, context):
        query = update.callback_query
        try:
            if await asyncio.to_thread(Path(get_hermes_home()).resolve) != self._reminder_home:
                raise ValueError('reminder_profile_mismatch')
            match = re.fullmatch(r'wr:([cd]):([a-f0-9]{32})', query.data or '')
            message = query.message
            sender = getattr(message, 'from_user', None)
            if not match or not sender or not sender.is_bot or sender.id != context.bot.id:
                raise ValueError('invalid_reminder_callback')
            result = await self._db(controls.operate, match.group(1), match.group(2),
                                    actor_id=query.from_user.id, chat_id=message.chat.id,
                                    thread_id=getattr(message, 'message_thread_id', None),
                                    message_id=message.message_id, bot_id=context.bot.id)
            if result['status'] in ('closed', 'already_closed'):
                if match.group(1) == 'c':
                    # Keep the clicked message/keyboard until other parts are deleted, so failures stay retryable.
                    ids = [int(mid) for mid in dict.fromkeys(result['message_ids'])
                           if int(mid) != message.message_id] + [message.message_id]
                    try:
                        await self._delete_notifications(context.bot, message.chat.id, ids)
                    except Exception as exc:
                        logger.warning('Reminder notification deletion failed: %s', type(exc).__name__)
                        warning = 'Вопрос закрыт, но удалить уведомление не удалось. Нажми «Закрыть» ещё раз.'
                        try:
                            await query.answer(warning, show_alert=True)
                        except Exception as ack_exc:
                            logger.warning('Reminder deletion warning acknowledgement failed: %s', type(ack_exc).__name__)
                            await self.send(str(message.chat.id), warning,
                                            metadata={'thread_id': str(message.message_thread_id)})
                    else:
                        with suppress(Exception):
                            await query.answer('Закрыто.' if result['status'] == 'closed' else 'Уже закрыто.')
                else:
                    await query.answer('Уже закрыто.')
                    with suppress(Exception):
                        await query.edit_message_reply_markup(reply_markup=None)
            elif result['status'] == 'already_requested':
                await query.answer('Черновик уже запрошен в этом чате.')
            else:
                accepted = False
                try:
                    # UI acknowledgement failure must not lose an authenticated request.
                    with suppress(Exception):
                        await query.answer('Запрашиваю черновик в этом чате. Собеседнику он не отправляется.')
                    source = self.build_source(chat_id=str(message.chat.id), chat_type='dm',
                                               user_id=str(query.from_user.id),
                                               user_name=query.from_user.full_name,
                                               thread_id=str(message.message_thread_id))
                    event = MessageEvent(text=result['prompt'], source=source,
                                         message_id=str(message.message_id), raw_message=update,
                                         metadata={'reminder_draft_key': result['key'],
                                                   'reminder_button': match.group(2)})
                    accepted = self._admit_draft(event)
                finally:
                    await self._db(controls.draft_admitted, result['key'], accepted)
                if not accepted:
                    await self.send(str(message.chat.id), 'Не удалось поставить запрос на черновик. Нажми кнопку ещё раз.',
                                    metadata={'thread_id': str(message.message_thread_id)})
        except ValueError:
            await query.answer('Эта кнопка недоступна в данном чате или для данного пользователя.', show_alert=True)
        except Exception as exc:
            logger.warning('Reminder callback failed: %s', type(exc).__name__)
            with suppress(Exception):
                await query.answer('Не удалось обработать кнопку. Статус черновика не подтверждён.', show_alert=True)
        raise ApplicationHandlerStop

    async def _delete_notifications(self, bot, chat_id, message_ids):
        for mid in message_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=mid)
            except BadRequest as exc:
                if 'message to delete not found' not in str(exc).lower():
                    raise
