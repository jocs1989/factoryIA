from pathlib import Path

from scripts.smoke_llm import main, read_allowed


def test_solo_se_cargan_las_variables_permitidas(tmp_path: Path) -> None:
    env = tmp_path / "env"
    env.write_text(
        "# comentario\n"
        "OPENAI_API_KEY='sk-fake'\n"
        'export OPENAI_MODEL="gpt-x"\n'
        "MONGO_URI=mongodb://secreto\n"
        "OTRA_COSA=1\n"
        "LLM_MODEL=\n"
        "linea sin igual\n"
    )
    assert read_allowed(env) == {
        "OPENAI_API_KEY": "sk-fake",
        "OPENAI_MODEL": "gpt-x",
    }


def test_sin_clave_falla_limpio_y_no_imprime_nada_sensible(
    tmp_path: Path, capsys, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env = tmp_path / "env"
    env.write_text("MONGO_URI=mongodb://secreto\n")
    assert main(["--env-file", str(env)]) == 2
    out = capsys.readouterr().out
    assert "falta OPENAI_API_KEY" in out and "secreto" not in out


def test_la_clave_no_se_exporta_al_entorno(
    tmp_path: Path, monkeypatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    import os

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env = tmp_path / "env"
    env.write_text("OPENAI_API_KEY=sk-fake\n")
    main(["--env-file", str(env), "--scenario", "99"])  # sale antes de llamar
    assert "OPENAI_API_KEY" not in os.environ
    assert "sk-fake" not in capsys.readouterr().out
