"""
Leverages Tests4Py to evaluate PCR and compare its performance against the underlying SFL technique.
"""

import json
import os
import shutil
import time
import traceback
from pathlib import Path
from typing import Optional, Tuple

from sflkit import Config, Analyzer
from sflkit.analysis.analysis_type import AnalysisType
from sflkit.analysis.factory import LineFactory
from sflkit.analysis.spectra import Spectrum
from sflkit.evaluation import Rank, Scenario
from sflkit.events.event_file import EventFile
from sflkit.events.mapping import EventMapping
from sflkit.language.language import Language
from sflkit.runners import PytestRunner
from tests4py import api as t4p
from tests4py.environment import env_on, activate_venv
from tests4py.projects import Project, TestStatus
from tests4py.sfl import (
    get_events_path,
    SFLInstrumentReport,
    SFLEventsReport,
    DEFAULT_TIME_OUT,
    instrument,
)
from tests4py.sfl.constants import DEFAULT_EXCLUDES
from tests4py.tests.utils import get_pytest_skip

from tcp import purify_tests


def parse_test_id(test_id: str) -> tuple:
    """
    Parse a test identifier into components.

    Args:
        test_id: Test identifier (e.g., "file.py::test_func[params]" or "file.py::Class::test_method[params]")

    Returns:
        Tuple of (file, class_name, test_name, param_suffix)
        class_name is None for module-level functions
        param_suffix is None for non-parameterized tests
    """
    # Extract parameter suffix if present (e.g., [1-hello])
    param_suffix = None
    test_id_base = test_id
    if "[" in test_id and test_id.endswith("]"):
        bracket_pos = test_id.rfind("[")
        param_suffix = test_id[bracket_pos + 1 : -1]
        test_id_base = test_id[:bracket_pos]

    parts = test_id_base.split("::")

    if len(parts) == 3:
        # Class method: file::class::method
        return parts[0], parts[1], parts[2], param_suffix
    elif len(parts) == 2:
        # Module-level function: file::function
        return parts[0], None, parts[1], param_suffix
    else:
        # Unknown format
        return None, None, None, None


def purify(
    project: Project,
    identifier: str,
    report: dict,
    enable_slicing: bool = True,
):
    # Initialize report for this project
    report[identifier]["time"] = dict()

    # Step 1: Checkout the project
    original_checkout = Path("tmp", f"{identifier}")
    if not original_checkout.exists():
        r = t4p.checkout(project)
        if r.successful:
            report[identifier]["checkout"] = "successful"
        else:
            report[identifier]["checkout"] = "failed"
            report[identifier]["error"] = traceback.format_exception(r.raised)
            return None
        original_checkout = r.location
    else:
        report[identifier]["checkout"] = "cached"

    r = t4p.build(original_checkout)
    if not r.successful:
        report[identifier]["build"] = "failed"
        report[identifier]["error"] = traceback.format_exception(r.raised)
        return None
    report[identifier]["build"] = "successful"

    venv_env = env_on(project)
    venv_env = activate_venv(original_checkout, venv_env)

    purified_tests_dir = Path("tmp", f"{identifier}_purified")
    purified_tests_dir.mkdir(parents=True, exist_ok=True)

    test_base = original_checkout / (project.test_base or Path("tests"))
    if test_base.is_file():
        test_base = test_base.parent

    start = time.time()
    # noinspection PyBroadException
    try:
        purified_mapping = purify_tests(
            src_dir=original_checkout,
            dst_dir=purified_tests_dir,
            failing_tests=project.test_cases,
            enable_slicing=enable_slicing,
            test_base=test_base,
            venv=venv_env,
        )
        report[identifier]["time"]["purification"] = time.time() - start
        report[identifier]["purification"] = "successful"
        report[identifier]["purified_tests"] = {
            test_id: [
                {
                    "file": str(purified_file.relative_to(purified_tests_dir)),
                    "params": param_suffix,
                }
                for purified_file, param_suffix in file_param_tuples
            ]
            for test_id, file_param_tuples in purified_mapping.items()
        }
        return purified_mapping
    except:
        report[identifier]["time"]["purification"] = time.time() - start
        report[identifier]["purification"] = "failed"
        report[identifier]["error"] = traceback.format_exc()
    return None


def update_project_purified(
    project: Project,
    identifier: str,
    path: Path,
    purified_mapping: dict[str, list[Tuple[Path, Optional[str]]]],
):
    purified_tests_dir = Path("tmp", f"{identifier}_purified")
    test_base_sfl = path / (project.test_base or Path("tests"))
    try:
        test_base_sfl.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        test_base_sfl = test_base_sfl.parent

    for item in purified_tests_dir.rglob("*"):
        if item.is_file():
            rel_path = item.relative_to(purified_tests_dir)
            dst = test_base_sfl / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dst)

    failing_tests = []
    relevant_files = (
        set(project.relevant_test_files) if project.relevant_test_files else set()
    )
    for test_id in project.test_cases:
        file_path, class_name, test_name, param_suffix = parse_test_id(test_id)
        if file_path is None:
            continue
        if test_id not in purified_mapping:
            continue
        for purified_file, purified_param_suffix in purified_mapping[test_id]:
            rel_path = purified_file.relative_to(purified_tests_dir)
            purified_file_full = test_base_sfl / rel_path
            purified_file_rel = purified_file_full.relative_to(path)
            if class_name:
                base_test_id = f"{purified_file_rel}::{class_name}::{test_name}"
            else:
                base_test_id = f"{purified_file_rel}::{test_name}"
            if purified_param_suffix:
                purified_test_id = f"{base_test_id}[{purified_param_suffix}]"
            else:
                purified_test_id = base_test_id

            failing_tests.append(purified_test_id)
            relevant_files.add(purified_test_id)
    project.test_cases = failing_tests
    project.relevant_test_files = relevant_files


def create_config(
    project: Project,
    src: Path,
    dst: Path,
    metrics: str = None,
    events_path: Optional[Path] = None,
    mapping: Optional[Path] = None,
    include_suffix: bool = False,
):
    if project.included_files:
        includes = project.included_files
        excludes = project.excluded_files
    elif project.excluded_files:
        includes = list()
        excludes = project.excluded_files
    else:
        includes = list()
        excludes = DEFAULT_EXCLUDES
    test_files = list({str(file.split("::")[0]) for file in project.test_cases})
    return Config.create(
        path=str(src.absolute()),
        language="python",
        events="line",
        metrics=metrics or "",
        predicates="line",
        passing=str(
            get_events_path(
                project=project,
                passing=True,
                events_path=events_path,
                include_suffix=include_suffix,
            )
        ),
        failing=str(
            get_events_path(
                project=project,
                passing=False,
                events_path=events_path,
                include_suffix=include_suffix,
            )
        ),
        working=str(dst.absolute()),
        include='"' + '","'.join(includes) + '"',
        exclude='"' + '","'.join(excludes) + '"',
        test_files='"' + '","'.join(test_files) + '"',
        mapping_path=str(mapping.absolute()) if mapping else "",
    )


def sflkit_instrument(
    project: Project,
    src: os.PathLike,
    dst: os.PathLike,
    mapping: os.PathLike,
):
    report = SFLInstrumentReport()
    work_dir = Path(src)
    try:
        if dst is None:
            raise ValueError("Destination required for instrument")
        report.project = project
        instrument(
            create_config(
                project,
                work_dir,
                Path(dst),
                mapping=Path(mapping) if mapping else None,
            ),
        )
        report.successful = True
    except BaseException as e:
        report.raised = e
        report.successful = False
    return report


def sflkit_unittest(
    work_dir: os.PathLike,
    project: Project,
    output: Path = None,
):
    report = SFLEventsReport()
    work_dir = Path(work_dir)
    try:
        if output is None:
            output = get_events_path(project, include_suffix=True)
        report.project = project
        environ = env_on(project)
        environ = activate_venv(work_dir, environ)
        runner = PytestRunner(timeout=DEFAULT_TIME_OUT)
        k = None
        if project.skip_tests:
            k = get_pytest_skip(project.skip_tests)
        files = project.relevant_test_files
        runner.run(
            directory=work_dir,
            output=output,
            files=files,
            base=project.test_base,
            environ=environ,
            k=k,
        )
        report.successful = True
        report.passing = runner.passing_tests
        report.failing = runner.failing_tests
        report.undefined = runner.undefined_tests
    except BaseException as e:
        report.raised = e
        report.successful = False
    return report


def build(
    project: Project,
    identifier: str,
    report: dict,
):
    path = Path("tmp", f"{identifier}")
    mapping = Path("mappings", f"{project}.json")
    os.makedirs("mappings", exist_ok=True)
    sfl_path = Path("tmp", f"sfl_{identifier}")
    start = time.time()
    r = sflkit_instrument(
        project,
        path,
        sfl_path,
        mapping=mapping,
    )
    report[identifier]["time"]["instrument"] = time.time() - start
    if r.successful:
        report[identifier]["build"] = "successful"
    else:
        report[identifier]["build"] = "failed"
        report[identifier]["error"] = traceback.format_exception(r.raised)
        return

    with open(mapping, "r") as f:
        mapping_content = json.load(f)
    with open(mapping, "w") as f:
        json.dump(mapping_content, f, indent=1)


def collect(
    project: Project,
    identifier: str,
    report: dict,
    tcp: bool = False,
):
    sfl_path = Path("tmp", f"sfl_{identifier}")
    if tcp:
        events_base = Path(
            "sflkit_events", project.project_name, "tcp", str(project.bug_id)
        )
    else:
        events_base = Path("sflkit_events", project.project_name, str(project.bug_id))

    # Step 7: Run tests to collect events
    shutil.rmtree(events_base, ignore_errors=True)
    start = time.time()
    r = sflkit_unittest(
        sfl_path,
        project,
        output=events_base,
    )
    report[identifier]["time"]["test"] = time.time() - start
    if r.successful:
        report[identifier]["test"] = "successful"
    else:
        report[identifier]["test"] = "failed"
        report[identifier]["error"] = traceback.format_exception(r.raised)
        return events_base

    return events_base


def get_events(
    project_name: str,
    bug_id=None,
):
    report_dir = Path("reports")
    report_dir.mkdir(exist_ok=True)
    report_file = report_dir / f"{project_name}.json"

    if report_file.exists():
        with open(report_file, "r") as f:
            report = json.load(f)
    else:
        report = {}

    for project in t4p.get_projects(project_name, bug_id):
        try:
            identifier = project.get_identifier()
            # Skip if already processed successfully
            if (
                identifier in report
                and "check" in report[identifier]
                and report[identifier]["check"] == "successful"
            ):
                print(f"Skipping {identifier} - already processed")
                continue

            report[identifier] = {}

            # Check project status
            if (
                project.test_status_buggy != TestStatus.FAILING
                or project.test_status_fixed != TestStatus.PASSING
            ):
                report[identifier]["status"] = "skipped"
                print(f"Skipping {identifier} - invalid test status")
                continue

            report[identifier]["status"] = "running"

            # Run the purification and event collection pipeline
            try:
                purified_mapping = purify(
                    project,
                    identifier,
                    report,
                    enable_slicing=True,
                )
                if purified_mapping is None:
                    report[identifier]["status"] = "error"
                    continue

                build(
                    project,
                    identifier,
                    report,
                )
                if report[identifier]["build"] != "successful":
                    report[identifier]["status"] = "error"
                    print("Build failed for", identifier)
                    continue

                events_path = collect(
                    project,
                    identifier,
                    report,
                    tcp=False,
                )

                if events_path is None:
                    report[identifier]["status"] = "error"
                    print("Event collection failed for", identifier)
                    continue
                else:
                    print("Collected events for", identifier)

                update_project_purified(
                    project,
                    identifier,
                    Path("tmp", f"sfl_{identifier}"),
                    purified_mapping,
                )
                print("Updated project purified for", identifier)
                events_path = collect(
                    project,
                    identifier,
                    report,
                    tcp=True,
                )
                if events_path is None:
                    report[identifier]["status"] = "error"
                    print("TCP Event collection failed for", identifier)
                    continue
                else:
                    print("Collected TCP events for", identifier)

                report[identifier]["check"] = "successful"
                report[identifier]["status"] = "completed"
            except Exception as e:
                report[identifier]["status"] = "error"
                report[identifier]["error"] = traceback.format_exception(e)
                print(f"Skipping {identifier} - {e}")
        finally:
            # Save report after each project
            with open(report_file, "w") as f:
                json.dump(report, f, indent=1)

    print("Event collection completed.")


def get_event_files(
    events: os.PathLike, mapping: os.PathLike | EventMapping
) -> tuple[list[EventFile], list[EventFile], list[EventFile]]:
    events = Path(events)
    if isinstance(mapping, EventMapping):
        mapping = mapping
    else:
        mapping = EventMapping.load_from_file(Path(mapping))
    if (events / "failing").exists():
        failing = [
            EventFile(
                events / "failing" / path,
                run_id,
                mapping,
                failing=True,
            )
            for run_id, path in enumerate(os.listdir(events / "failing"), start=0)
        ]
    else:
        failing = []
    if (events / "passing").exists():
        passing = [
            EventFile(events / "passing" / path, run_id, mapping, failing=False)
            for run_id, path in enumerate(
                os.listdir(events / "passing"),
                start=len(failing),
            )
        ]
    else:
        passing = []
    if (events / "undefined").exists():
        undefined = [
            EventFile(events / "undefined" / path, run_id, mapping, failing=False)
            for run_id, path in enumerate(
                os.listdir(events / "undefined"),
                start=len(failing) + len(passing),
            )
        ]
    else:
        undefined = []
    return failing, passing, undefined


def analyze_project(
    project: Project,
    analysis_file: os.PathLike,
    report: dict,
    tcp: bool = False,
) -> Analyzer:
    os.makedirs("analysis", exist_ok=True)
    if tcp:
        events = Path(
            "sflkit_events",
            project.project_name,
            "tcp",
            str(project.bug_id),
        )
    else:
        events = Path(
            "sflkit_events",
            project.project_name,
            str(project.bug_id),
        )
    mapping_file = Path("mappings", f"{project}.json")
    if not events.exists():
        raise FileNotFoundError(f"Events not found for {project}")
    if not mapping_file.exists():
        raise FileNotFoundError(f"Mapping not found for {project}")
    failing, passing, undefined = get_event_files(events, mapping_file)
    start = time.time()
    analyzer = Analyzer(
        relevant_event_files=failing,
        irrelevant_event_files=passing,
        factory=LineFactory(),
    )
    analyzer.analyze()
    report[project.get_identifier()][f"lines{'_tcp' if tcp else ''}"] = (
        time.time() - start
    )
    analyzer.dump(analysis_file, indent=1)
    return analyzer


def analyze(project_name, bug_id=None):
    report = dict()
    report_dir = Path("reports")
    os.makedirs(report_dir, exist_ok=True)
    for project in t4p.get_projects(project_name, bug_id):
        print(f"{project.get_identifier()} - {project.bug_id}")
        if (
            project.test_status_buggy != TestStatus.FAILING
            or project.test_status_fixed != TestStatus.PASSING
        ):
            continue
        project.buggy = True
        report[project.get_identifier()] = dict()
        for tcp in [True, False]:
            suffix = "_tcp" if tcp else ""
            analysis_file = Path("analysis", f"{project}{suffix}.json")
            if analysis_file.exists():
                continue
            analyze_project(project, analysis_file, report, tcp=tcp)

    with open(report_dir / f"analysis_{project_name}.json", "w") as f:
        json.dump(report, f, indent=1)


def get_results_for_type(
    type_,
    analyzer,
    project,
    location,
    faulty_lines,
    eval_metric=max,
):
    results = dict()
    times = dict()
    for metric in [
        Spectrum.Tarantula,
        Spectrum.Ochiai,
    ]:
        results[metric.__name__] = dict()
        time_start = time.time()
        suggestions = analyzer.get_sorted_suggestions(location, metric, type_)
        times[metric.__name__] = time.time() - time_start
        rank = Rank(
            suggestions, total_number_of_locations=project.loc, metric=eval_metric
        )
        for scenario in Scenario:
            results[metric.__name__][scenario.value] = {
                "top-1": rank.top_n(faulty_lines, 1, scenario, repeat=10000),
                "top-5": rank.top_n(faulty_lines, 5, scenario, repeat=10000),
                "top-10": rank.top_n(faulty_lines, 10, scenario, repeat=10000),
                "exam": rank.exam(faulty_lines, scenario),
                "wasted-effort": rank.wasted_effort(faulty_lines, scenario),
            }
    return results, times


def evaluate(project_name, bug_id, start=None, end=None):
    Language.PYTHON.setup()
    os.makedirs("results", exist_ok=True)
    reports_dir = Path("reports")
    os.makedirs(reports_dir, exist_ok=True)
    report_file = reports_dir / f"suggestion_{project_name}.json"
    time_report = dict()
    for project in t4p.get_projects(project_name, bug_id):
        if start is not None and project.bug_id < start:
            continue
        if end is not None and project.bug_id > end:
            continue
        results_file = Path("results", f"{project.get_identifier()}.json")
        if results_file.exists():
            continue
        results = dict()
        print(f"Evaluating {project}")
        if (
            project.test_status_buggy != TestStatus.FAILING
            or project.test_status_fixed != TestStatus.PASSING
        ):
            continue
        project.buggy = True
        subject_results = dict()
        subject_times = dict()
        location = Path("tmp", project.get_identifier())
        if not location.exists():
            report = t4p.checkout(project)
            if not report.successful:
                raise report.raised
            location = report.location
        for tcp in [True, False]:
            suffix = "_tcp" if tcp else ""
            analysis_file = Path("analysis", f"{project}{suffix}.json")
            if analysis_file.exists():
                analyzer = Analyzer.load(analysis_file)
            else:
                continue
            faulty_lines = set(t4p.get_faulty_lines(project))
            (
                subject_results[f"line{suffix}"],
                subject_times[f"line{suffix}"],
            ) = get_results_for_type(
                AnalysisType.LINE, analyzer, project, location, faulty_lines
            )
        results[project.get_identifier()] = subject_results
        time_report[project.get_identifier()] = subject_times
        with open(results_file, "w") as f:
            json.dump(results, f, indent=1)
    with open(report_file, "w") as f:
        json.dump(time_report, f, indent=1)


subjects = [
    "fastapi",
    "httpie",
    "tqdm",
]

metrics = [
    Spectrum.Tarantula.__name__,
    Spectrum.Ochiai.__name__,
]
scenarios = [scenario.value for scenario in Scenario]

localizations = ["top-1", "top-5", "top-10", "exam", "wasted-effort"]


def summarize_all():
    results_dir = Path("results")
    if not results_dir.exists():
        return
    results = {
        "subjects": list(),
        **{
            f"line{'_tcp' if tcp else ''}": {
                metric: {
                    scenario: {m: {"avg": 0.0, "all": list()} for m in localizations}
                    for scenario in scenarios
                }
                for metric in metrics
            }
            for tcp in [False, True]
        },
    }
    number_of_subjects = 0
    for subject in subjects:
        for i in range(100):
            subject_results = results_dir / f"{subject}_{i}.json"
            if not subject_results.exists():
                continue
            with subject_results.open() as f:
                subject_data = json.load(f)
            for s in subject_data:
                results["subjects"].append(s)
                number_of_subjects += 1
                for tcp in [False, True]:
                    t = f"line{'_tcp' if tcp else ''}"
                    for m in metrics:
                        for sce in scenarios:
                            for loc in localizations:
                                results[t][m][sce][loc]["all"].append(
                                    subject_data[s][t][m][sce][loc]
                                )

    for tcp in [False, True]:
        t = f"line{'_tcp' if tcp else ''}"
        for m in metrics:
            for sce in scenarios:
                for loc in localizations:
                    results[t][m][sce][loc]["avg"] = (
                        sum(results[t][m][sce][loc]["all"]) / number_of_subjects
                    )
    for m in metrics:
        for sce in scenarios:
            for loc in localizations:
                print(
                    f"{m} | {sce} | {loc} | Line | Avg: {results['line'][m][sce][loc]['avg']:.4f} | TCP Avg: {results['line_tcp'][m][sce][loc]['avg']:.4f}"
                )
    with open("summary.json", "w") as f:
        json.dump(results, f, indent=1)


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=["collect", "analyze", "evaluate", "summarize"]
    )
    parser.add_argument("-p", "--project", type=str, default=None, help="Project name")
    parser.add_argument("-i", "--bug-id", type=int, help="Bug ID")

    args = parser.parse_args()
    if args.action == "collect":
        if args.project is None:
            raise ValueError("Project name is required for collection")
        get_events(args.project, args.bug_id)
    elif args.action == "analyze":
        if args.project is None:
            raise ValueError("Project name is required for analysis")
        analyze(args.project, args.bug_id)
    elif args.action == "evaluate":
        if args.project is None:
            raise ValueError("Project name is required for evaluation")
        evaluate(args.project, args.bug_id)
    elif args.action == "summarize":
        summarize_all()


if __name__ == "__main__":
    main()
