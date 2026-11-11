"""Core projection interop: scalar normalization must not erase human facts."""
import pytest
from test_provider_egress import capture, texts


@pytest.mark.parametrize('provider',['honcho','openviking'])
def test_normalized_scalar_matches_last_user_without_rewriting_human_bytes(plugins,provider):
    rows=[{'role':'user','content':'old'},{'role':'assistant','content':'old answer'},
          {'role':'user','content':'  human\n  '},{'role':'assistant','content':'final'}]
    assert texts(capture(plugins,provider,rows,user='human'))==['  human\n  ','final']


@pytest.mark.parametrize('provider',['honcho','openviking'])
def test_authoritative_typed_ask_preserves_human_not_rendered_scaffolding(plugins,provider):
    rows=[{'role':'user','display_kind':'skill_invocation','display_metadata':{'typed_ask':'  human  '},'content':'RAW_SKILL_SCAFFOLD'},
          {'role':'assistant','content':'final'}]
    assert texts(capture(plugins,provider,rows,user='human'))==['  human  ','final']


@pytest.mark.parametrize('provider',['honcho','openviking'])
def test_core_projected_mixed_spans_match_normalized_scalar(plugins,provider):
    rows=[{'role':'user','content':'  before\n'},{'role':'user','content':'\nafter  '},{'role':'assistant','content':'final'}]
    assert texts(capture(plugins,provider,rows,user='before\n\nafter'))==['  before\n','\nafter  ','final']
