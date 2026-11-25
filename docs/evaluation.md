# Evaluation

## The three question sets

- `questions_dev.jsonl`: the only set I tune thresholds on.
- `questions_test.jsonl`: written before the first full run and frozen in git.
  The headline numbers come from this one.
- `questions_postfail.jsonl`: written after looking at my own failures. Reported
  on its own, never mixed into the test numbers.

## Metrics

TBD: how each metric is computed, and how retrieval misses are told apart from
generation misses.
