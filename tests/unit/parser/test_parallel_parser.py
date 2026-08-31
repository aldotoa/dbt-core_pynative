import datetime
import os
import shutil
import sys
import tempfile
import unittest
from argparse import Namespace
from unittest import mock



from dbt.clients.orjson_helper import (
    has_orjson,
    orjson_dumps,
    orjson_dumps_bytes,
    orjson_loads,
)
from dbt.config.project import Project
from dbt.contracts.files import FileHash, FilePath, ParseFileType, SchemaSourceFile, SourceFile
from dbt.contracts.graph.manifest import Manifest
from dbt.contracts.graph.nodes import DependsOn, Macro
from dbt.flags import set_from_args
from dbt.node_types import NodeType
from dbt.parser.concurrency import get_parser_concurrency, mp_parallel_map, parallel_map
from dbt.parser.macros import MacroParser
from dbt.parser.manifest import resolve_macro_depends_on
from dbt.parser.read_files import ReadFilesFromFileSystem, normalize_file_contents
from dbt.parser.search import FileBlock


def _standalone_square(x: int) -> int:
    return x * x


class TestParserConcurrency(unittest.TestCase):
    def test_get_parser_concurrency_default(self):
        concurrency = get_parser_concurrency()
        self.assertGreaterEqual(concurrency, 1)
        self.assertLessEqual(concurrency, 32)

    def test_get_parser_concurrency_env_var(self):
        with mock.patch.dict(os.environ, {"DBT_PARSER_CONCURRENCY": "8"}):
            with mock.patch("dbt.parser.concurrency.get_flags", side_effect=Exception("No flags")):
                concurrency = get_parser_concurrency()
                self.assertEqual(concurrency, 8)

    def test_get_parser_concurrency_single_threaded(self):
        flags = Namespace(SINGLE_THREADED=True, PARSER_CONCURRENCY=8)
        with mock.patch("dbt.parser.concurrency.get_flags", return_value=flags):
            concurrency = get_parser_concurrency()
            self.assertEqual(concurrency, 1)

    def test_parallel_map_order_and_results(self):
        items = list(range(100))

        def square(x):
            return x * x

        # Test single worker
        seq_results = parallel_map(square, items, max_workers=1)
        self.assertEqual(seq_results, [x * x for x in items])

        # Test multi-worker
        par_results = parallel_map(square, items, max_workers=4)
        self.assertEqual(par_results, seq_results)

    def test_parallel_map_empty(self):
        self.assertEqual(parallel_map(lambda x: x, []), [])

    def test_parallel_map_single_item(self):
        self.assertEqual(parallel_map(lambda x: x + 1, [42]), [43])

    def test_parallel_map_exception_propagation(self):
        def bad_func(x):
            if x == 5:
                raise ValueError("Intentional error at 5")
            return x

        with self.assertRaises(ValueError):
            parallel_map(bad_func, list(range(10)), max_workers=4)

    def test_mp_parallel_map(self):
        items = list(range(50))
        results = mp_parallel_map(_standalone_square, items, max_workers=2)
        self.assertEqual(results, [x * x for x in items])


class TestOrjsonHelper(unittest.TestCase):
    def test_dumps_and_loads(self):
        data = {
            "name": "my_model",
            "count": 42,
            "tags": ["tag1", "tag2"],
            "created": datetime.datetime(2026, 1, 1, 12, 0, 0),
        }
        serialized = orjson_dumps(data)
        self.assertIsInstance(serialized, str)
        deserialized = orjson_loads(serialized)
        self.assertEqual(deserialized["name"], "my_model")
        self.assertEqual(deserialized["count"], 42)
        self.assertEqual(deserialized["tags"], ["tag1", "tag2"])
        self.assertEqual(deserialized["created"], "2026-01-01T12:00:00")

    def test_dumps_bytes(self):
        data = {"key": "value"}
        serialized = orjson_dumps_bytes(data)
        self.assertIsInstance(serialized, bytes)
        deserialized = orjson_loads(serialized)
        self.assertEqual(deserialized, data)

    def test_set_and_nested_serialization(self):
        data = {"unique_set": {1, 2, 3}}
        serialized = orjson_dumps(data)
        deserialized = orjson_loads(serialized)
        self.assertEqual(sorted(deserialized["unique_set"]), [1, 2, 3])


class TestParallelFileProcessing(unittest.TestCase):
    def test_parallel_file_hashing(self):
        sample_files = [
            (f"models/model_{i}.sql", f"select {i} as col, '{i}' as str_col")
            for i in range(50)
        ]

        def process_file(item):
            rel_path, content = item
            fp = FilePath(
                searched_path="models",
                relative_path=rel_path,
                modification_time=0.0,
                project_root="/tmp/fake_proj",
            )
            normalized = normalize_file_contents(content)
            checksum = FileHash.from_contents(normalized)
            sf = SourceFile(
                path=fp,
                checksum=checksum,
                parse_file_type=ParseFileType.Model,
                project_name="fake_proj",
                contents=content,
            )
            return sf

        # Sequential
        seq_files = [process_file(item) for item in sample_files]
        # Parallel
        par_files = parallel_map(process_file, sample_files, max_workers=4)

        self.assertEqual(len(seq_files), len(par_files))
        for sf1, sf2 in zip(seq_files, par_files):
            self.assertEqual(sf1.file_id, sf2.file_id)
            self.assertEqual(sf1.checksum.checksum, sf2.checksum.checksum)
            self.assertEqual(sf1.contents, sf2.contents)

    def test_parallel_macro_parsing(self):
        macro_sources = [
            (
                f"macros/macro_{i}.sql",
                f"{{% macro my_macro_{i}(arg1, arg2) %}} select {i} + arg1 + arg2 {{% endmacro %}}",
            )
            for i in range(25)
        ]

        mock_project = mock.MagicMock(spec=Project)
        mock_project.project_name = "test_project"

        manifest = Manifest()
        parser = MacroParser(mock_project, manifest)

        tasks = []
        for rel_path, contents in macro_sources:
            fp = FilePath(
                searched_path="macros",
                relative_path=rel_path,
                modification_time=0.0,
                project_root="/tmp/fake_proj",
            )
            sf = SourceFile(
                path=fp,
                checksum=FileHash.from_contents(contents),
                parse_file_type=ParseFileType.Macro,
                project_name="test_project",
                contents=contents,
            )
            manifest.files[sf.file_id] = sf
            tasks.append((parser, sf.file_id))

        def _parse_task(t):
            p, file_id = t
            block = FileBlock(manifest.files[file_id])
            p.parse_file(block)
            return file_id

        results = parallel_map(_parse_task, tasks, max_workers=4)
        self.assertEqual(len(results), 25)
        self.assertEqual(len(manifest.macros), 25)

        for i in range(25):
            unique_id = f"macro.test_project.my_macro_{i}"
            self.assertIn(unique_id, manifest.macros)
            macro = manifest.macros[unique_id]
            self.assertEqual(macro.name, f"my_macro_{i}")
            self.assertEqual(len(macro.arguments), 2)
            self.assertEqual(macro.arguments[0].name, "arg1")
            self.assertEqual(macro.arguments[1].name, "arg2")

    def test_parallel_read_files_from_filesystem(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            models_dir = os.path.join(tmp_dir, "models")
            macros_dir = os.path.join(tmp_dir, "macros")
            seeds_dir = os.path.join(tmp_dir, "seeds")
            os.makedirs(models_dir)
            os.makedirs(macros_dir)
            os.makedirs(seeds_dir)

            # Create 30 model files
            for i in range(30):
                with open(os.path.join(models_dir, f"model_{i}.sql"), "w") as f:
                    f.write(f"select {i} as id, 'model_{i}' as name")

            # Create 10 macro files
            for i in range(10):
                with open(os.path.join(macros_dir, f"macro_{i}.sql"), "w") as f:
                    f.write(f"{{% macro custom_macro_{i}() %}} 'macro_{i}' {{% endmacro %}}")

            # Create 5 seed files
            for i in range(5):
                with open(os.path.join(seeds_dir, f"seed_{i}.csv"), "w") as f:
                    f.write(f"id,val\n1,{i}\n2,{i * 2}\n")

            mock_project = mock.MagicMock(spec=Project)
            mock_project.project_name = "demo_proj"
            mock_project.project_root = tmp_dir
            mock_project.model_paths = ["models"]
            mock_project.macro_paths = ["macros"]
            mock_project.seed_paths = ["seeds"]
            mock_project.snapshot_paths = []
            mock_project.analysis_paths = []
            mock_project.docs_paths = []
            mock_project.asset_paths = []
            mock_project.test_paths = []
            mock_project.function_paths = []
            mock_project.osi_paths = []
            mock_project.dbt_project_validate = True
            mock_project.packages_install_path = "dbt_packages"

            reader = ReadFilesFromFileSystem(all_projects={"demo_proj": mock_project})
            reader.read_files()

            self.assertEqual(len(reader.files), 45)
            self.assertEqual(len(reader.project_parser_files["demo_proj"]["ModelParser"]), 30)
            self.assertEqual(len(reader.project_parser_files["demo_proj"]["MacroParser"]), 10)
            self.assertEqual(len(reader.project_parser_files["demo_proj"]["SeedParser"]), 5)
        finally:
            shutil.rmtree(tmp_dir)
