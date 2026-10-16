from typer.testing import CliRunner

from getcraft.cli import app
from getcraft.config import load, save


def test_cli():
    assert CliRunner().invoke(app, ["--help"]).exit_code == 0


def test_config_roundtrip(tmp_path):
    path = tmp_path / "config.toml"
    data = load(path)
    data["platforms"] = {"linux": True}
    save(path, data)
    assert load(path) == data
