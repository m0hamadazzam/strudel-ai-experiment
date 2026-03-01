"""
Validator regression tests.

Every snippet here is valid Strudel REPL code. The validator must accept all of
them.  If any test fails, the validator is too strict and will inflate the
repair-call rate in production.
"""

import pytest

from backend.copilot import validate_generated_code

# A representative allowed-name set (core Strudel functions + synonyms).
# In production this is loaded from the DB; here we use a hand-curated subset
# that covers the patterns below.
ALLOWED = {
    # core
    "s", "n", "note", "stack", "cat", "seq", "stepcat", "arrange", "silence",
    # timing / tempo
    "setcpm", "fast", "slow", "early", "late", "hurry", "linger",
    # modulation
    "every", "sometimes", "rarely", "almostAlways", "almostNever",
    "often", "degradeBy", "choose", "wchoose",
    # transform
    "rev", "jux", "off", "ply", "chop", "striate", "bite", "splice",
    # pitch
    "transpose", "scale", "scaleTranspose", "octave",
    # effects / filters
    "lpf", "hpf", "bpf", "vowel", "shape", "crush", "distort", "gain",
    "pan", "postgain", "room", "roomsize", "roomfade",
    "delay", "delayfeedback", "delaytime",
    # envelope
    "attack", "decay", "sustain", "release", "adsr",
    # synth / samples
    "bank", "sound", "wt", "source", "samples",
    # utility
    "setcpm", "squeeze",
    # synonyms
    "cutoff", "lp", "hp", "bp", "dist", "att",
    "slowcat", "randcat", "sound",
}


class TestValidatorAcceptsValidStrudel:
    """Each test is a real Strudel snippet that MUST pass validation."""

    def test_basic_sound_pattern(self):
        code = 's("bd sd hh cp")'
        assert validate_generated_code(code, ALLOWED).ok

    def test_note_pattern(self):
        code = 'note("c3 eb3 g3").slow(2)'
        assert validate_generated_code(code, ALLOWED).ok

    def test_stack(self):
        code = 'stack(s("bd sd"), note("c3 e3 g3"))'
        assert validate_generated_code(code, ALLOWED).ok

    def test_euclidean_rhythm(self):
        code = 's("bd(3,8) sd(2,8) hh(5,8)")'
        r = validate_generated_code(code, ALLOWED)
        assert r.ok, f"Euclidean mini-notation falsely rejected: {r.errors}"

    def test_euclidean_complex(self):
        code = 's("bd(3,8) cp(1,8) [hh(5,8) oh(2,8)]")'
        assert validate_generated_code(code, ALLOWED).ok

    def test_method_chaining_effects(self):
        code = 's("bd sd").lpf(800).room(0.5).gain(0.8)'
        assert validate_generated_code(code, ALLOWED).ok

    def test_setcpm(self):
        code = "setcpm(130/4)"
        assert validate_generated_code(code, ALLOWED).ok

    def test_dollar_sign_pattern(self):
        code = '$: s("bd sd")'
        assert validate_generated_code(code, ALLOWED).ok

    def test_dollar_sign_note(self):
        code = '$: note("c3 eb3 g3").lpf(1200)'
        assert validate_generated_code(code, ALLOWED).ok

    def test_arrow_function_in_every(self):
        code = 's("bd sd hh cp").every(4, x => x.fast(2))'
        assert validate_generated_code(code, ALLOWED).ok

    def test_sometimes_with_rev(self):
        code = 's("hh*8").sometimes(rev)'
        assert validate_generated_code(code, ALLOWED).ok

    def test_mini_notation_operators(self):
        code = 's("hh*8")'
        assert validate_generated_code(code, ALLOWED).ok

    def test_mini_notation_alternation(self):
        code = 's("<bd sd> hh")'
        assert validate_generated_code(code, ALLOWED).ok

    def test_mini_notation_grouping(self):
        code = 's("[bd sd] hh [cp oh]")'
        assert validate_generated_code(code, ALLOWED).ok

    def test_mini_notation_rest(self):
        code = 's("bd ~ sd ~")'
        assert validate_generated_code(code, ALLOWED).ok

    def test_mini_notation_weight(self):
        code = 's("bd@3 sd@1")'
        assert validate_generated_code(code, ALLOWED).ok

    def test_let_variable(self):
        code = 'let kick = s("bd").fast(2)'
        assert validate_generated_code(code, ALLOWED).ok

    def test_const_variable(self):
        code = 'const melody = note("c3 e3 g3")'
        assert validate_generated_code(code, ALLOWED).ok

    def test_multiline_multi_dollar(self):
        code = (
            'setcpm(128/4)\n'
            '$: s("bd(3,8) sd(2,8)").gain(0.9)\n'
            '$: note("c2 [eb2 g2]").s("sawtooth").lpf(800).room(0.3)\n'
            '$: s("hh*8").gain(0.6).pan("0.3 0.7")'
        )
        assert validate_generated_code(code, ALLOWED).ok

    def test_chained_delay(self):
        code = 's("cp").delay(0.5).delayfeedback(0.4).delaytime(0.125)'
        assert validate_generated_code(code, ALLOWED).ok

    def test_filter_sweep(self):
        code = 'note("c2 c2 c2 c2").s("sawtooth").lpf("400 800 1200 2000")'
        assert validate_generated_code(code, ALLOWED).ok

    def test_jux_rev(self):
        code = 's("bd sd hh cp").jux(rev)'
        assert validate_generated_code(code, ALLOWED).ok

    def test_degradeBy(self):
        code = 's("hh*16").degradeBy(0.5)'
        assert validate_generated_code(code, ALLOWED).ok

    def test_striate(self):
        code = 's("breaks165").chop(16).every(4, x => x.striate(4))'
        assert validate_generated_code(code, ALLOWED).ok

    def test_scale(self):
        code = 'note("0 2 4 6").scale("C:minor").slow(2)'
        assert validate_generated_code(code, ALLOWED).ok

    def test_bank(self):
        code = 's("bd sd hh oh").bank("RolandTR909")'
        assert validate_generated_code(code, ALLOWED).ok

    def test_adsr_envelope(self):
        code = 'note("c3").s("sawtooth").attack(0.1).decay(0.2).sustain(0.5).release(0.3)'
        assert validate_generated_code(code, ALLOWED).ok

    def test_arrange(self):
        code = (
            'let a = s("bd sd")\n'
            'let b = note("c3 e3")\n'
            'arrange([4, a], [4, b])'
        )
        assert validate_generated_code(code, ALLOWED).ok

    def test_cat_patterns(self):
        code = 'cat(s("bd sd"), s("hh hh hh hh"), s("cp"))'
        assert validate_generated_code(code, ALLOWED).ok

    def test_math_in_pattern(self):
        code = 'setcpm(Math.floor(140/4))'
        assert validate_generated_code(code, ALLOWED).ok


class TestValidatorRejectsInvalid:
    """Code using forbidden patterns or unknown functions must be rejected."""

    def test_reject_require(self):
        code = 'const fs = require("fs")'
        r = validate_generated_code(code, ALLOWED)
        assert not r.ok

    def test_reject_import(self):
        code = 'import { something } from "module"'
        r = validate_generated_code(code, ALLOWED)
        assert not r.ok

    def test_reject_process(self):
        code = 'process.exit(1)'
        r = validate_generated_code(code, ALLOWED)
        assert not r.ok

    def test_reject_unknown_function(self):
        code = 'makeAwesomeBeat("techno")'
        r = validate_generated_code(code, ALLOWED)
        assert not r.ok
        assert "makeAwesomeBeat" in r.invalid_names

    def test_returns_all_invalid_names(self):
        code = 'fooBar(1)\nbazQux(2)'
        r = validate_generated_code(code, ALLOWED)
        assert not r.ok
        assert "fooBar" in r.invalid_names
        assert "bazQux" in r.invalid_names
        assert len(r.errors) >= 2

    def test_safe_js_builtins_allowed(self):
        code = 'setcpm(Math.floor(140/4))'
        r = validate_generated_code(code, ALLOWED)
        assert r.ok, f"Math.floor should be allowed: {r.errors}"
