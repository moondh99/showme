"""Scoring must distinguish correct status from weak text/geometry checks."""
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('showme_evaluation',Path(__file__).resolve().parents[1]/'scripts/evaluate_answers.py')
evaluation=importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


class EvaluationTests(unittest.TestCase):
    def test_percentile_uses_the_nearest_rank_for_small_samples(self):
        self.assertEqual(evaluation.percentile([1,2,3,4],.95),4)
        self.assertEqual(evaluation.percentile(list(range(1,49)),.95),46)
        with self.assertRaises(ValueError):
            evaluation.percentile([],.95)

    def test_iou_is_intersection_over_union(self):
        self.assertEqual(evaluation.iou([0,0,10,10],[0,0,10,10]),1)
        self.assertEqual(evaluation.iou([0,0,10,10],[20,20,30,30]),0)
        self.assertAlmostEqual(evaluation.iou([0,0,10,10],[5,0,15,10]),1/3)

    def test_correct_status_can_fail_location_check(self):
        expectation={'expected_status':'answered','required_answer_groups':[['노란','노랑']],'reference_box':[500,100,900,700]}
        answer={'status':'answered','answer':'노란 트레이입니다.','highlights':[{'box':[0,0,100,100]}]}
        result=evaluation.score(expectation,answer)
        self.assertTrue(result['status_match'])
        self.assertTrue(result['answer_terms_match'])
        self.assertFalse(result['geometry_pass'])
        self.assertFalse(result['automatic_checks_pass'])

    def test_unsupported_affirmative_answer_is_flagged(self):
        result=evaluation.score({'expected_status':'insufficient_information'},
            {'status':'answered','answer':'오전 9시입니다.','highlights':[]})
        self.assertTrue(result['inappropriate_answer'])
        self.assertFalse(result['automatic_checks_pass'])

if __name__=='__main__':unittest.main()
