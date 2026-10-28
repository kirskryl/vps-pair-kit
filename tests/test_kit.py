import base64
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('kit', ROOT / 'scripts/kit.py')
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)

class KitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copy(ROOT / '.env.example', self.root / '.env.example')
        shutil.copytree(ROOT / 'vps-pair', self.root / 'vps-pair')
        kit.init(self.root)

    def fill(self):
        for role in ('home','egress'):
            kit.write_private(self.root / (role + '.key'), 'test fixture, not a real private key')
        replacements = {'HOME_IP':'192.0.2.10','EGRESS_IP':'198.51.100.20','HOME_ADMIN':'homeadmin','EGRESS_ADMIN':'egressadmin','HOME_SSH_KEY':str(self.root/'home.key'),'EGRESS_SSH_KEY':str(self.root/'egress.key')}
        p = self.root / '.env'
        lines = p.read_text().splitlines()
        updated = []
        for line in lines:
            k = line.partition('=')[0]
            updated.append(k+'='+replacements[k] if k in replacements else line)
        p.write_text('\n'.join(updated)+'\n')
        return kit.validate(self.root)

    def test_init_private_random_idempotent(self):
        path = self.root / '.env'
        before = path.read_bytes()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        key = next(x.partition('=')[2] for x in path.read_text().splitlines() if x.startswith('SS2022_KEY='))
        self.assertEqual(len(base64.b64decode(key, validate=True)), 32)
        kit.init(self.root)
        self.assertTrue(before == path.read_bytes())

    def test_editor_requires_explicit_flag_and_no_shell(self):
        with patch.object(kit.subprocess, 'run') as run:
            kit.init(self.root)
            run.assert_not_called()
            with patch.dict(os.environ, {'VISUAL':'my-editor --wait'}):
                kit.init(self.root, True)
            self.assertTrue(run.call_args[1]['shell'] is False)
            self.assertEqual(run.call_args[0][0][-1], str(self.root / '.env'))

    def test_validation_rejects_missing_and_unsafe_permissions(self):
        with self.assertRaises(kit.Invalid):
            kit.validate(self.root)
        self.fill()
        (self.root / '.env').chmod(0o644)
        with self.assertRaises(kit.Invalid):
            kit.validate(self.root)

    def test_shell_substitution_is_data_never_executed(self):
        self.fill()
        p = self.root / '.env'
        p.write_text(p.read_text().replace('HOME_ADMIN=homeadmin', 'HOME_ADMIN=$(touch SENTINEL)'))
        with self.assertRaises(kit.Invalid):
            kit.validate(self.root)
        self.assertFalse((self.root/'SENTINEL').exists())

    def test_reject_invalid_key_root_duplicate_unknown_fields(self):
        self.fill()
        p = self.root / '.env'
        original = p.read_text()
        modifications = [original+'HOME_IP=192.0.2.1\n', original+'UNKNOWN=anything\n', original.replace('HOME_ADMIN=homeadmin','HOME_ADMIN=root'), original.replace(next(x for x in original.splitlines() if x.startswith('SS2022_KEY=')), 'SS2022_KEY=invalid')]
        for content in modifications:
            with self.subTest(case=modifications.index(content)):
                p.write_text(content)
                with self.assertRaises(kit.Invalid):
                    kit.validate(self.root)

    def test_reject_symlink_env_and_output(self):
        self.fill()
        p = self.root / '.env'
        p.rename(self.root/'realenv')
        p.symlink_to(self.root/'realenv')
        with self.assertRaises(kit.Invalid):
            kit.validate(self.root)
        p.unlink()
        (self.root/'realenv').rename(p)
        target = self.root/'other'
        target.mkdir(mode=0o700)
        (self.root/'.rendered').symlink_to(target, target_is_directory=True)
        with self.assertRaises(kit.Invalid):
            kit.render(self.root)

    def test_render_complete_private_pair_and_new_generation(self):
        self.fill()
        out = kit.render(self.root)
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o700)
        self.assertEqual(len(list(out.iterdir())), 4)
        for file in out.iterdir():
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
            self.assertFalse('__' in file.read_text())
        home = json.loads((out/'home.json').read_text())
        egress = json.loads((out/'egress.json').read_text())
        kit.policy(home, egress)
        # Avoid assertEqual values, which could print secrets on test failure.
        self.assertTrue(home['outbounds'][0]['password'] == egress['inbounds'][0]['password'])
        self.assertEqual(home['route'], {'final':'egress-ss'})
        self.assertEqual(home['inbounds'][0]['listen'], '127.0.0.1')
        self.assertNotEqual(out, kit.render(self.root))

    def test_independent_ssh_ports_default_and_custom(self):
        data = self.fill()
        self.assertEqual(data['HOME_SSH_PORT'], '22')
        self.assertEqual(data['EGRESS_SSH_PORT'], '22')
        p = self.root / '.env'
        original = p.read_text()
        p.write_text(original.replace('HOME_SSH_PORT=22', 'HOME_SSH_PORT=2222').replace('EGRESS_SSH_PORT=22', 'EGRESS_SSH_PORT=2200'))
        out = kit.render(self.root)
        ssh = (out / 'ssh-config').read_text()
        home, egress = ssh.split('Host pair-egress')
        self.assertIn('Port 2222', home)
        self.assertIn('Port 2200', egress)
        for field in ('HOME_SSH_PORT', 'EGRESS_SSH_PORT'):
            for value in ('0', '65536', '$(command)', '-1'):
                p.write_text(original.replace(field+'=22', field+'='+value))
                with self.subTest(field=field, invalid=value), self.assertRaises(kit.Invalid):
                    kit.validate(self.root)

    def test_fail_closed_rejects_direct_fallback_public_mixed_and_final_change(self):
        self.fill()
        out = kit.render(self.root)
        home = json.loads((out/'home.json').read_text())
        egress = json.loads((out/'egress.json').read_text())
        mutations = []
        x = copy.deepcopy(home); x['outbounds'].append({'type':'direct','tag':'direct'}); mutations.append(x)
        x = copy.deepcopy(home); x['route']['final']='direct'; mutations.append(x)
        x = copy.deepcopy(home); x['inbounds'][0]['listen']='0.0.0.0'; mutations.append(x)
        x = copy.deepcopy(home); x['outbounds'][0]['type']='urltest'; mutations.append(x)
        for index, mutated in enumerate(mutations):
            with self.subTest(case=index), self.assertRaises(kit.Invalid):
                kit.policy(mutated, egress)

    def test_cli_smoke_outputs_no_values(self):
        shutil.copytree(ROOT/'scripts', self.root/'scripts')
        data = self.fill()
        for cmd in ('check','validate','render'):
            result = subprocess.run([sys.executable, str(self.root/'scripts/kit.py'), cmd], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertFalse(data['SS2022_KEY'] in result.stdout + result.stderr)
        result = subprocess.run([sys.executable,str(self.root/'scripts/kit.py'),'check','--open'], text=True,capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(data['SS2022_KEY'] in result.stdout+result.stderr)

if __name__ == '__main__':
    unittest.main()
