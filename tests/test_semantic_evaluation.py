import importlib.util,json,hashlib
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('semantic_eval',ROOT/'scripts/evaluate_semantics.py')
eval=importlib.util.module_from_spec(spec);spec.loader.exec_module(eval)

class SemanticEvaluationTests(unittest.TestCase):
    def test_full_context_does_not_substitute_for_chosen_evidence(self):
        case={'expected_intent':'procedure','expected_status':'answered','required_quote_groups':[['별도 조건']]}
        answer={'status':'answered','answer':'다른 대상 규칙','evidence':[],
                'approved_context':[{'text':'별도 조건'}]}
        self.assertFalse(eval.score(case,answer,'procedure',None)['quote_coverage'])
    def test_missing_assessment_and_unsafe_permission_are_different(self):
        case={'expected_intent':'procedure','expected_status':'answered','expected_decision':'blocked'}
        answer={'status':'answered','answer':'규칙','evidence':[]}
        missing=eval.score(case,answer,'procedure',None)
        self.assertTrue(missing['assessment_absent']);self.assertFalse(missing['unsafe_permission'])
        unsafe=eval.score(case,answer,'procedure',{'decision':'allowed'})
        self.assertTrue(unsafe['unsafe_permission']);self.assertFalse(unsafe['all_checks_pass'])
    def test_frozen_data_hashes_and_splits(self):
        folder=ROOT/'evaluations/r10-r11-v1';manifest=json.loads((folder/'manifest.json').read_text())
        for name,digest in manifest['hashes'].items():
            self.assertEqual(hashlib.sha256((folder/name).read_bytes()).hexdigest(),digest)
        cases=json.loads((folder/'cases.json').read_text())
        self.assertEqual(len(cases),len({c['id'] for c in cases}))
        self.assertEqual({s:sum(c['split']==s for c in cases) for s in manifest['splits']},manifest['splits'])

if __name__=='__main__':unittest.main()
