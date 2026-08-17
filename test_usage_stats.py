import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

import usage_stats


class UsageStatsTests(unittest.TestCase):
    def setUp(self):
        for key in usage_stats.usage_total:
            usage_stats.usage_total[key]=0

    def test_read_usage_from_dict_with_nested_details(self):
        usage={
            "prompt_tokens":10,
            "completion_tokens":7,
            "total_tokens":17,
            "prompt_tokens_details":{"cached_tokens":3},
            "completion_tokens_details":{"reasoning_tokens":2},
        }

        self.assertEqual(
            usage_stats.read_usage(usage),
            {
                "input":10,
                "output":7,
                "total":17,
                "cached_input":3,
                "cache_miss_input":0,
                "reasoning":2,
            },
        )

    def test_read_usage_from_object_and_defaults(self):
        usage=SimpleNamespace(
            prompt_tokens=4,
            completion_tokens=5,
            total_tokens=9,
        )

        self.assertEqual(usage_stats.read_usage(usage), {
            "input":4,
            "output":5,
            "total":9,
            "cached_input":0,
            "cache_miss_input":0,
            "reasoning":0,
        })

    def test_display_usage_accumulates_and_preserves_output(self):
        current={
            "input":1,
            "output":2,
            "total":3,
            "cached_input":4,
            "cache_miss_input":5,
            "reasoning":6,
        }
        output=io.StringIO()

        with redirect_stdout(output):
            usage_stats.display_usage(current)
            usage_stats.display_usage(current)

        self.assertEqual(usage_stats.usage_total, {
            "input":2,
            "output":4,
            "total":6,
            "cached_input":8,
            "cache_miss_input":10,
            "reasoning":12,
        })
        self.assertIn("[usage] input=1 output=2 total=3", output.getvalue())
        self.assertIn("[usage cumulative] input=2 output=4 total=6", output.getvalue())


if __name__=="__main__":
    unittest.main()
