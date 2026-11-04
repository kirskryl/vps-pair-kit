import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('auto_publish_skill', ROOT / 'scripts/auto_publish_skill.py')
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


class AutoPublishTests(unittest.TestCase):
    def test_only_skill_documents_are_eligible(self):
        self.assertTrue(publish.skill_path('SKILL.md'))
        self.assertTrue(publish.skill_path('references/hermes-only.md'))
        self.assertFalse(publish.skill_path('scripts/kit.py'))
        self.assertFalse(publish.skill_path('.env'))
        self.assertFalse(publish.skill_path('references/secret.env'))

    def test_rejects_secret_and_broken_reference(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(publish, 'ROOT', Path(directory)):
            root = Path(directory)
            (root / 'SKILL.md').write_text('---\nname: vps-pair-kit\ndescription: test\n---\n')
            docs = root / 'references'
            docs.mkdir()
            page = docs / 'pipeline.md'
            page.write_text('TELEGRAM_BOT_TOKEN=' + 'x' * 20 + '\n')
            with self.assertRaisesRegex(ValueError, 'Возможный секрет'):
                publish.validate_files(['references/pipeline.md'])
            page.write_text('[несуществующий файл](missing.md)\n')
            with self.assertRaisesRegex(ValueError, 'Не найдена ссылка'):
                publish.validate_files(['references/pipeline.md'])
            page.write_text('[скилл](../SKILL.md)\n')
            publish.validate_files(['references/pipeline.md'])


if __name__ == '__main__':
    unittest.main()
