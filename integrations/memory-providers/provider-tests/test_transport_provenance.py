"""Typed transport provenance must remain meaningful at every serializer."""
import pytest
from test_provider_egress import capture, texts


@pytest.mark.parametrize('provider',['honcho','openviking'])
@pytest.mark.parametrize('kind',['tool_transport','reasoning','progress'])
def test_typed_message_kind_is_not_plain_conversation(plugins,provider,kind):
    rows=[{'role':'user','message_kind':kind,'content':'RAW_MACHINE'},{'role':'assistant','content':'RAW_DERIVED'}]
    assert capture(plugins,provider,rows,user='RAW_MACHINE',answer='RAW_DERIVED')==[]


@pytest.mark.parametrize('provider',['honcho','openviking'])
def test_typed_assistant_message_kind_is_not_final(plugins,provider):
    rows=[{'role':'user','content':'human'},{'role':'assistant','message_kind':'reasoning','content':'RAW_REASON'}]
    assert texts(capture(plugins,provider,rows))==['human']
