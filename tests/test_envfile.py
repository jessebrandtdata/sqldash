from sqldash.envfile import load_env_file


def test_env_file_sets_only_missing_names(tmp_path):
    p = tmp_path / "env"
    p.write_text('# c\n\nexport A=1\nB="two words"\nC=\'x\'\nBROKEN LINE\nD=keep=this\n')
    env = {"B": "already"}
    assert load_env_file(p, env) == ["A", "C", "D"]
    assert env == {"A": "1", "B": "already", "C": "x", "D": "keep=this"}


def test_env_file_missing_is_fine(tmp_path):
    assert load_env_file(tmp_path / "nope", {}) == []
