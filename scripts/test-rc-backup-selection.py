#!/usr/bin/env python3
"""Run the actual RC selection and filename observation with host XCTest transport fixtures."""
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
    echo_start = '    private func observeExportedFilename('
    echo_end = '\n    private func export('
    echo_marker = '    // RC_FILENAME_ECHO_BODY'
    if source.count(echo_start) != 1 or source.count(echo_end) != 1 or fixture.count(echo_marker) != 1:
        raise ValueError('Filename observer or fixture boundary changed')
    echo_first, echo_last = source.index(echo_start), source.index(echo_end)
    if echo_last <= echo_first:
        raise ValueError('Filename observer boundary order changed')
    echo_method = source[echo_first:echo_last]
    echo_body = re.sub(r'\b(XCUIApplication|XCUIElement)\b', lambda m: substitutions[m[0]], echo_method)
    record_start = '    private func openRecord('
    record_end = '\n    private func performBoundTap<Element>('
    record_marker = '    // RC_OPEN_RECORD_BODY'
    if source.count(record_start) != 1 or source.count(record_end) != 1 or fixture.count(record_marker) != 1:
        raise ValueError('Record transition or fixture boundary changed')
    record_first, record_last = source.index(record_start), source.index(record_end)
    if record_last <= record_first:
        raise ValueError('Record transition boundary order changed')
    record_method = source[record_first:record_last]
    record_body = re.sub(r'\b(XCUIApplication|XCUIElement)\b', lambda m: substitutions[m[0]], record_method)
    presentation_start = '    private func openExportDestination('
    presentation_end = '\n    private func observeExportedFilename('
    presentation_marker = '    // RC_EXPORT_DESTINATION_BODY'
    if (source.count(presentation_start) != 1 or source.count(presentation_end) != 1
            or fixture.count(presentation_marker) != 1):
        raise ValueError('Export destination or fixture boundary changed')
    presentation_first, presentation_last = source.index(presentation_start), source.index(presentation_end)
    if presentation_last <= presentation_first:
        raise ValueError('Export destination boundary order changed')
    presentation_method = source[presentation_first:presentation_last]
    presentation_body = re.sub(r'\b(XCUIApplication|XCUIElement)\b', lambda m: substitutions[m[0]], presentation_method)
    action_start = '    private func performBoundTap<Element>('
    action_end = '\n    private func openItem('
    action_marker = '    // RC_BOUND_ACTION_BODY'
    if source.count(action_start) != 1 or source.count(action_end) != 1 or fixture.count(action_marker) != 1:
        raise ValueError('Bound action method or fixture boundary changed')
    action_first, action_last = source.index(action_start), source.index(action_end)
    if action_last <= action_first:
        raise ValueError('Bound action method boundary order changed')
    action_method = source[action_first:action_last]
    folder_start = '    private func beginFolderCreation('
    folder_end = '\n    private func folder('
    folder_marker = '    // RC_FOLDER_CREATION_BODY'
    if source.count(folder_start) != 1 or source.count(folder_end) != 1 or fixture.count(folder_marker) != 1:
        raise ValueError('Folder creation route or fixture boundary changed')
    folder_first, folder_last = source.index(folder_start), source.index(folder_end)
    if folder_last <= folder_first:
        raise ValueError('Folder creation route boundary order changed')
    folder_method = source[folder_first:folder_last]
    folder_substitutions = {'XCUIApplication': 'FixtureApp', 'XCUIElement': 'FixtureFolderElement'}
    folder_body = re.sub(r'\b(XCUIApplication|XCUIElement)\b', lambda m: folder_substitutions[m[0]], folder_method)
    tests = (fixture.replace(marker, body).replace(echo_marker, echo_body)
             .replace(record_marker, record_body).replace(presentation_marker, presentation_body)
             .replace(action_marker, action_method).replace(folder_marker, folder_body))
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
        'filename_echo_method_sha256': digest(echo_method.encode()),
        'open_record_method_sha256': digest(record_method.encode()),
        'export_destination_method_sha256': digest(presentation_method.encode()),
        'bound_action_method_sha256': digest(action_method.encode()),
        'folder_creation_method_sha256': digest(folder_method.encode()),
        'folder_transport_type_substitutions': folder_substitutions,
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
