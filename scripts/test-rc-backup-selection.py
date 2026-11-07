#!/usr/bin/env python3
"""Run the actual RC selection body with host XCTest transport fixtures only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

from rc_acceptance_process import bounded_capture

ROOT = Path(__file__).resolve().parents[1]
INPUTS = (
    'Acceptance/RC/RCArtifactAcceptanceTests.swift',
    'UITests/Support/FilesNavigationReadiness.swift',
    'scripts/tests/fixtures/rc-backup-selection.swift',
)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def materialize(destination, inputs):
    source, helper, fixture = (inputs[path].decode('utf-8') for path in INPUTS)
    start = '    private func selectBackup('
    end = '\n    private func checkpoint('
    marker = '    // RC_SELECT_BACKUP_BODY'
    if source.count(start) != 1 or source.count(end) != 1 or fixture.count(marker) != 1:
        raise ValueError('Selection method or fixture boundary changed')
    first, last = source.index(start), source.index(end)
    if last <= first:
        raise ValueError('Selection method boundary order changed')
    method = source[first:last]
    # Rename types, never branches, expressions, assertions or operation order.
    substitutions = {'XCUIApplication': 'FixtureApp', 'XCUIElement': 'FixtureElement'}
    body = re.sub(r'\b(XCUIApplication|XCUIElement)\b', lambda m: substitutions[m[0]], method)
    if helper.count('final class FilesNavigationReadiness {') != 1:
        raise ValueError('Shared helper declaration changed')
    helper = re.sub(r'\bFilesNavigationReadiness\b', 'Readiness', helper)
    tests = fixture.replace(marker, body)
    cases = re.findall(r'    func (test\w+)\(', fixture)
    if not cases or len(cases) != len(set(cases)):
        raise ValueError('Expected fixture case identities are missing or ambiguous')
    directory = destination / 'Tests/RCBackupSelectionRegressionTests'
    directory.mkdir(parents=True)
    (destination / 'Package.swift').write_text(
        '// swift-tools-version: 6.0\nimport PackageDescription\n'
        'let package = Package(name: "RCBackupSelectionRegressionTests", '
        'platforms: [.macOS(.v14)], targets: [.testTarget(name: "RCBackupSelectionRegressionTests")])\n')
    (directory / 'Readiness.swift').write_text(helper)
    (directory / 'RCBackupSelectionRegressionTests.swift').write_text(tests)
    return {
        'method_sha256': digest(method.encode()),
        'transport_type_substitutions': substitutions,
        'shared_class_rename': 'FilesNavigationReadiness -> Readiness',
        'generated_sources': {p.name: digest(p.read_bytes()) for p in directory.iterdir()},
        'expected_cases': ['RCBackupSelectionRegressionTests.' + case for case in cases],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Host XCTest requires macOS and the selected Xcode; no Simulator is used')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    inputs = {path: (ROOT / path).read_bytes() for path in INPUTS}
    proof = {'schema_version': 1, 'status': 'FAIL', 'sources': {p: digest(raw) for p, raw in inputs.items()},
             'native_acceptance': False, 'app_launched': False, 'simulator_used': False}
    work = Path(tempfile.mkdtemp(prefix='host-', dir=output))
    operation = {}
    try:
        proof.update(materialize(work, inputs))
        bounded_capture(['/usr/bin/xcrun', 'swift', 'test', '--package-path', str(work)],
                        cwd=ROOT, env=dict(os.environ), timeout=180, limit=8 * 1024**2,
                        receipt=operation, stdout_path=output/'tests.stdout', stderr_path=output/'tests.stderr')
        log = (output/'tests.stdout').read_text() + (output/'tests.stderr').read_text()
        actual = re.findall(r"Test Case '-\[(?:\w+\.)?(\w+) (test\w+)\]' (passed|failed|skipped) ", log)
        proof['actual_cases'] = [{'name': cls+'.'+case, 'outcome': result} for cls, case, result in actual]
        proof['source_unchanged'] = all((ROOT/path).read_bytes() == raw for path, raw in inputs.items())
        if (sorted(cls+'.'+case for cls, case, _ in actual) != sorted(proof['expected_cases'])
                or any(result != 'passed' for _, _, result in actual) or not proof['source_unchanged']):
            raise ValueError('Exact current fixture outcomes or source preservation failed')
        proof['status'] = 'PASS'
    except Exception as error:
        proof['error_type'] = type(error).__name__
    finally:
        (output/'operation.json').write_text(json.dumps(operation, indent=2)+'\n')
        proof['operation_sha256'] = digest((output/'operation.json').read_bytes())
        proof['streams'] = {name: digest((output/name).read_bytes())
                            for name in ['tests.stdout', 'tests.stderr'] if (output/name).is_file()}
        closed = operation.get('cleanup', {}).get('success') is True
        if not operation or closed:
            shutil.rmtree(work)
        else:
            proof['retained_work_reason'] = 'Owned process closure unproved; preserve active path'
        proof['process_closed'] = closed
        if not closed:
            proof['status'] = 'FAIL'
        (output/'result.json').write_text(json.dumps(proof, indent=2)+'\n')
    print(json.dumps({'status': proof['status'], 'cases': len(proof.get('actual_cases', [])),
                      'process_closed': proof['process_closed'], 'native_acceptance': False}))
    return 0 if proof['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
