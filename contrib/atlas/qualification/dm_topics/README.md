# Private-topic regression

This offline cohort exercises the pinned native contract, admission gate, edge and real PTB serialization. Staff verification and the HTTP transport are isolated fixtures. It does not connect to Telegram or a model.

Set `ATLAS_TEST_RUNTIME` to the already approved Atlas runtime and use its prepared Python environment with PTB 22.8:

```sh
ATLAS_TEST_RUNTIME="$ATLAS_RUNTIME" "$ATLAS_NATIVE_PYTHON" -B qualification/dm_topics/test_dm_topics.py overlay
```

Expected result: nine passing tests. The causal old-contract control is:

```sh
ATLAS_TEST_RUNTIME="$ATLAS_RUNTIME" "$ATLAS_NATIVE_PYTHON" -B qualification/dm_topics/test_dm_topics.py baseline Topics.test_actual_sdk_private_topic_ingress
```

Expected result: `exact_dm_scope_required` before durable origin registration.

The fix admits only `None` or a canonical positive topic identifier in an authenticated private chat. The exact UID/chat/profile match, Staff proof, signatures, freshness, nonce handling and egress recipient/topic checks are unchanged. Separate private topics retain different native session keys.

The service-message test covers intake ordering and origin separation only. Suppression of an empty TopicCreate model turn is not qualified by this offline cohort.

After installation on both hosts, the operator's existing private topic was exercised through a fresh authenticated user message. The bot's exact requested reply was independently observed in that same topic, and the SDK delivery journal recorded its acknowledgement. The consumed original request was not replayed.
