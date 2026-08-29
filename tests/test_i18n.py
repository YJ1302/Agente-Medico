"""Interface language toggle — full-page English rendering."""

from __future__ import annotations

from app.i18n import translate_html


def test_translate_exact_and_phrase():
    html = (
        "<h1>Rotaciones</h1><p>No se encontraron rotaciones con los filtros aplicados.</p>"
        "<button>Guardar</button><span>Estado</span> y <b>Sede</b>"
        '<input placeholder="Interno o código">'
        "<div>30 resultado(s) · mostrando 1–12</div>"
    )
    out = translate_html(html)
    assert "<h1>Rotations</h1>" in out
    assert "No rotations found with the applied filters." in out
    assert ">Save<" in out and ">Status<" in out and ">Site<" in out
    assert 'placeholder="Intern or code"' in out
    assert "30 result(s)" in out


def test_translate_leaves_scripts_and_data_alone():
    html = (
        '<script>var t = "Rotaciones";</script>'
        "<td>Sin tutores.</td>"          # exact catalog hit -> translated
        "<b>Sede Central Norte</b>"       # data: 'Sede' must not match mid-string
        "<span>Sin tutor</span>"          # phrase, word-boundary guarded
    )
    out = translate_html(html)
    assert 'var t = "Rotaciones";' in out          # script untouched
    assert "<td>No tutors.</td>" in out
    assert "<b>Sede Central Norte</b>" in out       # data untouched
    assert "<span>No tutor</span>" in out


def test_toggle_renders_page_in_english(admin):
    admin.get("/set-lang?lang=en&next=/dashboard", follow_redirects=False)
    html = admin.get("/dashboard").text
    assert "Institutional dashboard" in html
    assert "INTERNSHIP MANAGEMENT" in html   # sidebar section
    assert "Active interns" in html          # server-generated stat card
    assert ">Rotations<" in html and ">Rotaciones<" not in html

    # Back to Spanish leaves the page in Spanish (translator not invoked).
    admin.get("/set-lang?lang=es&next=/dashboard", follow_redirects=False)
    assert "Dashboard institucional" in admin.get("/dashboard").text
