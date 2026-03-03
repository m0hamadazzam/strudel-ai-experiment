import unittest

from backend.patching import (
    apply_patch_operations,
    build_patch_operations,
    summarize_patch_operations,
)


class TestPatchUtils(unittest.TestCase):
    def test_build_patch_operations_insert(self):
        base = 's("bd")\n'
        target = 's("bd")\n$: note("c e g")\n'

        patch_ops = build_patch_operations(base, target)
        self.assertEqual(len(patch_ops), 1)
        self.assertEqual(patch_ops[0].op, "insert")
        self.assertEqual(apply_patch_operations(base, patch_ops), target)

    def test_build_patch_operations_replace(self):
        base = 's("bd sd")\n'
        target = 's("bd sd hh")\n'

        patch_ops = build_patch_operations(base, target)
        self.assertEqual(len(patch_ops), 1)
        self.assertEqual(patch_ops[0].op, "replace")
        self.assertEqual(apply_patch_operations(base, patch_ops), target)

    def test_build_patch_operations_delete(self):
        base = 's("bd")\n$: note("c")\n'
        target = 's("bd")\n'

        patch_ops = build_patch_operations(base, target)
        self.assertEqual(len(patch_ops), 1)
        self.assertEqual(patch_ops[0].op, "delete")
        self.assertEqual(apply_patch_operations(base, patch_ops), target)

    def test_summarize_patch_operations(self):
        base = 's("bd")\n'
        target = 's("bd hh")\n$: note("c e g")\n'
        patch_ops = build_patch_operations(base, target)

        stats = summarize_patch_operations(patch_ops)
        self.assertEqual(stats.operations, 1)
        self.assertEqual(stats.additions, 2)
        self.assertEqual(stats.deletions, 1)


if __name__ == "__main__":
    unittest.main()
