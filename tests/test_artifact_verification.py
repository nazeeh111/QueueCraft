"""Export verification must distinguish JSON types and refuse ambiguous documents."""
import contextlib
import io
import json

import pytest

from queuecraft import Event
from queuecraft.cli import main


@pytest.fixture
def exported(tmp_path):
    source = tmp_path / 'input.csv'
    source.write_text(Event(0, -1, 0, 'S', (('B', 100, 100_000), ('A', 102, 100_000))).csv())
    out = tmp_path / 'order'
    with contextlib.redirect_stdout(io.StringIO()):
        assert main(['simulate', str(source), '--size', '1', '--recording-end-ns', '5000000000', '--out', str(out)]) == 0
    return out


@pytest.mark.parametrize('change', ['bool_lots', 'float_lots', 'nested_bool', 'nested_float', 'duplicate_result', 'duplicate_config', 'float_schema'])
def test_verify_rejects_type_changes_and_duplicate_keys(exported, change):
    result = exported / 'result.json'
    config = exported / 'config.json'
    data = json.loads(result.read_text())
    if change == 'bool_lots':
        assert data['filled'] == 1
        data['filled'] = True
    elif change == 'float_lots':
        data['filled'] = 1.0
    elif change == 'nested_bool':
        assert data['fills'][0]['quantity'] == 1
        data['fills'][0]['quantity'] = True
    elif change == 'nested_float':
        data['ledger'][0]['cash'] = float(data['ledger'][0]['cash'])
    elif change == 'duplicate_result':
        result.write_text('{"filled":987,' + result.read_text()[1:])
    elif change == 'duplicate_config':
        config.write_text('{"schema_version":999,' + config.read_text()[1:])
    elif change == 'float_schema':
        document = json.loads(config.read_text())
        document['schema_version'] = 2.0
        config.write_text(json.dumps(document))
    if change in {'bool_lots', 'float_lots', 'nested_bool', 'nested_float'}:
        result.write_text(json.dumps(data))
    before = {p.name: p.read_bytes() for p in exported.iterdir()}
    output, error = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error), pytest.raises(SystemExit) as failure:
        main(['verify', str(exported)])
    assert failure.value.code == 2
    assert '"replay": "exact"' not in output.getvalue()
    assert {p.name: p.read_bytes() for p in exported.iterdir()} == before


def test_verify_accepts_object_key_reordering_and_whitespace(exported):
    result = exported / 'result.json'
    data = json.loads(result.read_text())
    result.write_text(json.dumps(dict(reversed(list(data.items()))), separators=(',', ':')))
    with contextlib.redirect_stdout(io.StringIO()) as output:
        assert main(['verify', str(exported)]) == 0
    assert json.loads(output.getvalue())['replay'] == 'exact'
