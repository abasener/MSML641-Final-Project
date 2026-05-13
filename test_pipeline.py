"""
Unit tests for the Astronomy KG QA pipeline.

These tests cover pure functions only. No models or KG file are loaded.
The integration/evaluation tests remain in the main notebook (TestJNB.ipynb).
"""

import sys
import types
import unittest

_tk = types.ModuleType("tkinter")
_tk.IntVar = _tk.Frame = _tk.Label = _tk.Button = _tk.Entry = object
_tk.Text = _tk.Radiobutton = _tk.Tk = object
sys.modules.setdefault("tkinter", _tk)
sys.modules.setdefault("tkinter.messagebox", types.ModuleType("tkinter.messagebox"))

import astronomy_gui as ag          # noqa: E402  (import after stub)
from fetch_objects import to_ttl_object  # noqa: E402


# ===========================================================================
# 1. _clean_value: strips DBpedia URIs and disambiguation suffixes
# ===========================================================================

class TestCleanValue(unittest.TestCase):

    def test_uri_plain(self):
        v = ag._clean_value("http://dbpedia.org/resource/Orion_Nebula")
        self.assertEqual(v, "Orion Nebula")

    def test_uri_with_disambiguation(self):
        # Parenthesised suffixes like _(moon) should be stripped
        v = ag._clean_value("http://dbpedia.org/resource/Europa_(moon)")
        self.assertEqual(v, "Europa")

    def test_uri_multi_word(self):
        v = ag._clean_value("http://dbpedia.org/resource/Andromeda_Galaxy")
        self.assertEqual(v, "Andromeda Galaxy")

    def test_plain_string_passthrough(self):
        # Non-URI strings should be returned unchanged
        v = ag._clean_value("228 K")
        self.assertEqual(v, "228 K")

    def test_empty_string(self):
        v = ag._clean_value("")
        self.assertEqual(v, "")


# ===========================================================================
# 2. detect_query_type: "filter" when a type word + constraint word appear,
#                       "lookup" otherwise
# ===========================================================================

class TestDetectQueryType(unittest.TestCase):

    def test_lookup_temperature(self):
        self.assertEqual(ag.detect_query_type("How hot is Mars?"), "lookup")

    def test_lookup_description(self):
        self.assertEqual(ag.detect_query_type("What is the Andromeda Galaxy?"), "lookup")

    def test_filter_stars_with_constraint(self):
        self.assertEqual(
            ag.detect_query_type("List stars with a temperature above 5000 K"), "filter"
        )

    def test_filter_planets_containing(self):
        self.assertEqual(
            ag.detect_query_type("Which planets contain hydrogen?"), "filter"
        )

    def test_lookup_no_constraint(self):
        # "galaxy" appears but no constraint word → lookup
        self.assertEqual(
            ag.detect_query_type("Tell me about the Whirlpool Galaxy"), "lookup"
        )


# ===========================================================================
# 3. format_template: formats pipeline output dicts into readable strings
# ===========================================================================

class TestFormatTemplate(unittest.TestCase):

    def _lookup(self, entity, intent, rows):
        """Helper: build the dict that answer_question() would return."""
        return {
            "query_type": "lookup",
            "results": [{"entity": entity, "intent": intent, "data": rows}],
        }

    def _filter(self, search_type, constraints, labels):
        return {
            "query_type": "filter",
            "filter_params": {"search_type": search_type, "constraints": constraints},
            "data": [{"label": l} for l in labels],
        }

    def test_temperature_template(self):
        out = ag.format_template(
            self._lookup("Mars", "temperature", [{"predicate": "meanTemperature", "value": "210"}])
        )
        self.assertIn("Mars", out)
        self.assertIn("210", out)

    def test_description_template(self):
        out = ag.format_template(
            self._lookup("Sirius", "description", [{"predicate": "description", "value": "A binary star system"}])
        )
        self.assertIn("Sirius", out)
        self.assertIn("binary star", out)

    def test_lookup_no_data_returns_not_found(self):
        out = ag.format_template(self._lookup("FakeObject", "temperature", []))
        self.assertIn("No", out)
        self.assertIn("FakeObject", out)

    def test_lookup_blank_value_skipped(self):
        # A row with an empty value should not appear in the output
        out = ag.format_template(
            self._lookup("Venus", "size", [
                {"predicate": "mass", "value": ""},
                {"predicate": "radius", "value": "6051.8 km"},
            ])
        )
        self.assertIn("6051.8", out)
        self.assertNotIn("mass", out.split("Venus")[1].split("radius")[0])

    def test_filter_returns_labels(self):
        constraints = [{"intent": "temperature", "comparison": ">", "values": ["5000"]}]
        out = ag.format_template(
            self._filter("dbo:Star", constraints, ["Sirius", "Vega"])
        )
        self.assertIn("Sirius", out)
        self.assertIn("Vega", out)

    def test_filter_no_results(self):
        constraints = [{"intent": "temperature", "comparison": ">", "values": ["999999"]}]
        out = ag.format_template(self._filter("dbo:Star", constraints, []))
        self.assertIn("No", out)

    def test_filter_deduplicates_labels(self):
        constraints = [{"intent": "location", "comparison": ">", "values": ["0"]}]
        out = ag.format_template(
            self._filter("dbo:Planet", constraints, ["Mars", "Mars", "Jupiter"])
        )
        # "Mars" should appear exactly once
        self.assertEqual(out.count("Mars"), 1)


# ===========================================================================
# 4. INTENT_MAP: every label maps to a known, non-empty intent string
# ===========================================================================

VALID_INTENTS = {"composition", "location", "temperature", "size",
                 "discovery", "description", "orbital"}

class TestIntentMap(unittest.TestCase):

    def test_all_labels_map_to_valid_intent(self):
        for label, intent in ag.INTENT_MAP.items():
            with self.subTest(label=label):
                self.assertIn(intent, VALID_INTENTS, f"'{label}' maps to unknown intent '{intent}'")

    def test_no_empty_labels(self):
        for label in ag.INTENT_MAP:
            self.assertTrue(label.strip(), "INTENT_MAP contains a blank label")

    def test_intent_labels_list_matches_map_keys(self):
        self.assertEqual(set(ag.INTENT_LABELS), set(ag.INTENT_MAP.keys()))


# ===========================================================================
# 5. INTENT_TO_PRED: every intent has at least one predicate
# ===========================================================================

class TestIntentToPred(unittest.TestCase):

    def test_all_intents_covered(self):
        for intent in VALID_INTENTS:
            with self.subTest(intent=intent):
                self.assertIn(intent, ag.INTENT_TO_PRED)
                self.assertGreater(len(ag.INTENT_TO_PRED[intent]), 0)

    def test_all_predicates_are_strings(self):
        for intent, preds in ag.INTENT_TO_PRED.items():
            for p in preds:
                with self.subTest(intent=intent, pred=p):
                    self.assertIsInstance(p, str)
                    self.assertTrue(p.startswith("dbo:") or p.startswith("dbp:"),
                                    f"Predicate '{p}' does not use a known prefix")


# ===========================================================================
# 6. to_ttl_object (fetch_objects.py): converts SPARQL result value dicts
#    to Turtle-format strings
# ===========================================================================

class TestToTtlObject(unittest.TestCase):

    def test_uri(self):
        val = {"type": "uri", "value": "http://dbpedia.org/resource/Hydrogen"}
        self.assertEqual(to_ttl_object(val), "<http://dbpedia.org/resource/Hydrogen>")

    def test_literal_with_language(self):
        val = {"type": "literal", "value": "The Sun", "xml:lang": "en"}
        self.assertEqual(to_ttl_object(val), '"The Sun"@en')

    def test_literal_with_datatype(self):
        val = {
            "type": "literal",
            "value": "5778",
            "datatype": "http://www.w3.org/2001/XMLSchema#integer",
        }
        result = to_ttl_object(val)
        self.assertIn("5778", result)
        self.assertIn("^^", result)

    def test_plain_literal(self):
        val = {"type": "literal", "value": "some text"}
        self.assertEqual(to_ttl_object(val), '"some text"')

    def test_double_quote_escaped(self):
        val = {"type": "literal", "value": 'He said "hello"'}
        result = to_ttl_object(val)
        self.assertIn('\\"', result)

    def test_newline_escaped(self):
        val = {"type": "literal", "value": "line one\nline two"}
        result = to_ttl_object(val)
        self.assertIn("\\n", result)


# ===========================================================================
# 7. kg_label_fallback: string-match fallback when NER finds no entities
# ===========================================================================

class TestKgLabelFallback(unittest.TestCase):

    def setUp(self):
        """Build a tiny in-memory RDF graph with two English labels."""
        import rdflib
        self.g = rdflib.Graph()
        self.g.parse(data="""
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            <http://dbpedia.org/resource/Mars>
                rdfs:label "Mars"@en ;
                rdfs:label "Marte"@es .
            <http://dbpedia.org/resource/Andromeda_Galaxy>
                rdfs:label "Andromeda Galaxy"@en .
        """, format="turtle")
        # Temporarily point ag.g at our mini graph
        self._orig_g = ag.g
        ag.g = self.g

    def tearDown(self):
        ag.g = self._orig_g

    def test_single_match(self):
        matches = ag.kg_label_fallback("How far is Mars from Earth?", self.g)
        self.assertIn("Mars", matches)

    def test_multi_word_label_matched(self):
        matches = ag.kg_label_fallback("Tell me about the Andromeda Galaxy", self.g)
        self.assertIn("Andromeda Galaxy", matches)

    def test_non_english_label_excluded(self):
        # "Marte" is Spanish — should not appear
        matches = ag.kg_label_fallback("Marte es un planeta", self.g)
        self.assertNotIn("Marte", matches)

    def test_no_match_returns_empty(self):
        matches = ag.kg_label_fallback("What is the speed of light?", self.g)
        self.assertEqual(matches, [])

    def test_longer_label_first(self):
        # "Andromeda Galaxy" should come before "Andromeda" if both matched
        matches = ag.kg_label_fallback("Tell me about the Andromeda Galaxy", self.g)
        if len(matches) > 1:
            self.assertGreaterEqual(len(matches[0]), len(matches[1]))


# ===========================================================================
# Standalone runner (no pytest needed)
# ===========================================================================

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()
    for cls in [
        TestCleanValue, TestDetectQueryType, TestFormatTemplate,
        TestIntentMap, TestIntentToPred, TestToTtlObject, TestKgLabelFallback,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
