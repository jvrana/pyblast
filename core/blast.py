# More information: https://www.ncbi.nlm.nih.gov/guide/howto/run-blast-local/
# BLAST User Manual: https://www.ncbi.nlm.nih.gov/books/NBK1762/
import tempfile
import json
from .seqio import *
from .utils import *


# custom output format: https://www.ncbi.nlm.nih.gov/books/NBK279682/


class Blast(object):
    """
    A Blast initializer for running blast searches against subjects contained in a directory.
    """

    blast_config = {
        "outfmt": "\"7 qacc sacc score evalue bitscore" +
                  "length nident gapopen gaps qlen qstart qend" +
                  "slen sstart send sstrand qseq sseq\""
    }

    def __init__(self, dn_name, subj_in_dir, query_path, db_output_directory, results_out_path, **config):
        """
        A Blast initializer for running blast searches.
        :param dn_name: Name for database file structure. This name will be appended to all db files that blast creates.
        :param subj_in_dir: Input directory containing a list of subjects to align against the query
        :param query_path: Location of the fasta or genbank file containing the query
        :param db_output_directory: Location to store database related files
        :param results_out_path: Path to store the results.out file. Path can be absolute or relative.
        :param config: Additional configurations to run for the blast search (see
        https://www.ncbi.nlm.nih.gov/books/NBK279682/)
        """
        self.name = dn_name
        self.path_to_input_dir = os.path.abspath(subj_in_dir)
        self.path_to_query = os.path.abspath(query_path)
        self.config = Blast.blast_config
        if config is not None:
            self.config.update(config)
        self.path_to_output_dir = os.path.abspath(db_output_directory)
        self.db = os.path.join(db_output_directory, dn_name)
        self.path_to_input_seq_file = None
        self.db_input_metadata = None
        self.results = None #
        self.raw_results = None
        self.input_sequences = []
        self.results_out_path = os.path.abspath(results_out_path)
        self.validate_files()

    def validate_files(self):
        def _is_file(f):
            return os.path.isfile(os.path.abspath(f))

        def _is_dir(d):
            return os.path.isdir(os.path.abspath(d))

        outdir = split_path(self.results_out_path)[0]
        errors = []
        for f in [self.path_to_query]:
            if not _is_file(f):
                errors.append("File not found: {}".format(f))
        for d in [outdir, self.path_to_output_dir, self.path_to_input_dir]:
            if not _is_dir(d):
                errors.append("Directory not found {}".format(d))
        if len(errors) > 0:
            raise ValueError("\n".join(errors))

    def create_config(self):
        d = {
            "db": self.db,
            "out": self.results_out_path,
            "query": self.path_to_query,
        }
        d.update(self.config)
        return d

    def quick_blastn(self):
        self.makedb()
        self.blastn()
        self.parse_results()

    def blastn(self):
        self.run_cmd("blastn", **self.create_config())
        with open(self.results_out_path, 'rU') as handle:
            self.raw_results = handle.read()

    # Wrapper for the util.run_cmd
    def run_cmd(self, cmd, **kwargs):
        run_cmd(cmd, **kwargs)

    def concat_templates(self):
        out = self.db + '.fsa'
        fasta, seqs, metadata = concat_seqs(self.path_to_input_dir, out, savemeta=True)
        self.db_input_metadata = metadata
        self.input_sequences = seqs
        return out, seqs, metadata

    def makedb(self):
        out, seqs, metadata = self.concat_templates()
        return self.fasta_to_db(out)

    def fasta_to_db(self, fasta):
        self.run_cmd("makeblastdb", dbtype="nucl", title=self.name, out=self.db, **{"in": fasta})
        self.path_to_input_seq_file = fasta
        return self.db

    def parse_results(self, save_as_json=True, delim=','):
        """
        Parses the raw blast txt output as a json
        :param save_as_json: If True, save output to results.json located in same directory as results_out_path
        :param delim: Deliminter for parsing blast output (default: ',')
        :return: The result as a dictionary or list
        """
        def cleanup_fields(match_fields, replacements=None):
            if replacements is None:
                replacements = {
                    ('.', ''),
                    (' ', '_'),
                    ('%', 'perc')
                }
            for i, f in enumerate(match_fields):
                for r in replacements:
                    match_fields[i] = f.replace(r[0], r[1])
            return match_fields

        def extract_metadata(r, delim=','):
            g = re.search(
                '#\s*(?P<blast_ver>.+)\n' +
                '# Query:\s*(?P<query>.*)\n' +
                '# Database:\s*(?P<database>.+)\n' +
                '# Fields:\s*(?P<fields>.+)',
                r)
            metadata = g.groupdict()
            # clean up fields
            metadata['fields'] = re.split('\s*{}\s*'.format(delim), metadata['fields'])
            metadata['fields'] = cleanup_fields(metadata['fields'])
            return g.groupdict()

        def extract_raw_matches(r):
            return re.findall('\n([^#].*)', r)

        def validate_matches(raw_matches, fields):
            match_dicts = []
            for m in raw_matches:
                values = [str_to_f_to_i(v) for v in m.split('\t')]
                match_dicts.append(dict(list(zip(fields, values))))
            return match_dicts

        # print(self.results)
        results = self.raw_results
        if results.strip() == '':
            return {}
        meta = extract_metadata(results, delim)
        fields = meta['fields']
        raw_matches = extract_raw_matches(results)
        match_dicts = validate_matches(raw_matches, fields)

        if save_as_json:
            dir, filename, basename, ext = split_path(self.results_out_path)
            with open(os.path.join(dir, basename + ".json"), 'w') as handle:
                json.dump(match_dicts, handle)
        return match_dicts

    def __str__(self):
        return "{}".format(self.create_config())


class Aligner(Blast):
    """
    A Blast object that stores the database files in a hidden temporary directory. Use entry points
    "quick_blastn" for returning results as a python object.
    """
    def __init__(self, dn_name, subj_in_dir, query_path, **config):
        """
        Aligner: A Blast object that stores the database files in a hidden temporary directory.
        :param dn_name: Name for database file structure. This name will be appended to all db files that blast creates.
        :param subj_in_dir: Input directory containing a list of subjects to align against the query
        :param query_path: Location of the fasta or genbank file containing the query
        :param config: Additional configurations to run for the blast search (see
        https://www.ncbi.nlm.nih.gov/books/NBK279682/)
        """
        db_output_directory = tempfile.mkdtemp()
        out = tempfile.mktemp(dir=db_output_directory)
        super(Aligner, self).__init__(dn_name, subj_in_dir, query_path, db_output_directory, out, **config)
