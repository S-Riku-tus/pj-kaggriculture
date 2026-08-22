from __future__ import annotations

from scripts.run_match import import_agent


def test_import_agent_preserves_file_location(tmp_path) -> None:
    source = tmp_path / "main.py"
    source.write_text(
        "def agent(obs):\n"
        "    return {'module_file': __file__, 'observation': obs}\n",
        encoding="utf-8",
    )
    loaded = import_agent(source)
    result = loaded({"step": 3})
    assert result["module_file"] == str(source)
    assert result["observation"] == {"step": 3}
