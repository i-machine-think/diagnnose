import os
import warnings
from typing import Dict, List, NamedTuple, Optional, Tuple
from unidecode import unidecode

import inflect
from torchtext.data import Example, Field

from diagnnose.corpus import Corpus
from diagnnose.typedefs.models import LanguageModel

from ..task import DownstreamTask, DownstreamCorpora


class RawItem(NamedTuple):
    """ The original corpus structure contains these 18 fields. """

    sentence: str
    orig_sentence: str
    pos_sentence: str
    subj: str
    verb: str
    subj_pos: str
    has_rel: str
    has_nsubj: str
    verb_pos: str
    subj_index: str
    verb_index: str
    n_intervening: str
    last_intervening: str
    n_diff_intervening: str
    distance: str
    max_depth: str
    all_nouns: str
    nouns_up_to_verb: str


class LinzenDownstream(DownstreamTask):
    """

    Parameters
    ----------
    """

    def __init__(
        self,
        model: LanguageModel,
        vocab_path: str,
        corpus_path: str,
        subtasks: Optional[List[str]] = None,
    ):
        super().__init__(model, vocab_path, corpus_path, subtasks=subtasks)

    def initialize(
        self,
        corpus_path: str,
        subtasks: Optional[List[str]] = None,
        items_per_subtask: Optional[int] = 1000,
    ) -> DownstreamCorpora:
        """ Performs the initialization for the tasks of
        Marvin & Linzen (2018)

        Arxiv link: https://arxiv.org/pdf/1808.09031.pdf

        Repo: https://github.com/BeckyMarvin/LM_syneval

        Parameters
        ----------
        corpus_path : str
            Path to directory containing the Marvin datasets that can be
            found in the github repo.
        subtasks : List[str], optional
            The downstream tasks that will be tested. If not provided this
            will default to the full set of conditions.
        items_per_subtask : int, optional
            Number of items that is selected per subtask. If not
            provided the full subtask set will be used instead.

        Returns
        -------
        corpora : Dict[str, Corpus]
            Dictionary mapping a subtask to a Corpus.
        """
        subtasks = subtasks or ["SS", "SP", "PS", "PP", "SPP", "PSS", "SPPP", "PSSS"]

        corpora: DownstreamCorpora = self.create_corpora(
            corpus_path, subtasks, items_per_subtask
        )

        return corpora

    def create_corpora(
        self, corpus_path: str, subtasks: List[str], items_per_subtask: Optional[int]
    ) -> DownstreamCorpora:
        raw_corpora: Dict[str, List[RawItem]] = self.create_raw_corpora(
            corpus_path, subtasks
        )

        corpora = {}
        verb_inflections = self.create_verb_inflections(corpus_path)

        for condition, items in raw_corpora.items():
            corpus = self.create_corpus(items, verb_inflections, items_per_subtask)

            n_attractors = str(len(condition))
            corpora.setdefault(n_attractors, {})[condition] = corpus

        return corpora

    def create_raw_corpora(self, corpus_path, subtasks) -> Dict[str, List[RawItem]]:
        raw_corpora = {}

        with open(os.path.join(corpus_path, "agr_50_mostcommon_10K.tsv")) as f:
            next(f)  # skip header
            for line in f:
                item: RawItem = RawItem(*line.strip().split("\t"))
                sva_condition = self.item_to_sva_condition(item)
                if self.item_to_sva_condition(item) in subtasks:
                    raw_corpora.setdefault(sva_condition, []).append(item)

        return raw_corpora

    @staticmethod
    def item_to_sva_condition(item: RawItem) -> str:
        """ Maps an item to an SVA condition, based on the POS tags of
        the sentence between the subject and the main verb.

        For example:
        The_DT men_NNS under_IN the_DT bridge_NN walk_VBP
        is mapped to "PS": a plural subject with 1 singular attractor.
        """
        pos_sen = item.pos_sentence.split()
        pos_subsen = pos_sen[int(item.subj_index) - 1 : int(item.verb_index)]

        pos_mapping = {"NNS": "P", "NN": "S"}
        sva_condition = "".join([pos_mapping.get(t, "") for t in pos_subsen])

        return sva_condition

    def create_corpus(
        self,
        items: List[RawItem],
        verb_inflections: Dict[str, str],
        items_per_subtask: Optional[int],
    ) -> Corpus:
        header = ["sen", "token", "wrong_token"]
        fields = Corpus.create_fields(header, tokenize_columns=header)

        examples: List[Optional[Example]] = [
            self.item_to_example(item, fields, verb_inflections) for item in items
        ]

        examples: List[Example] = list(filter(None, examples))

        if items_per_subtask is not None:
            examples = examples[:items_per_subtask]

        corpus = Corpus(
            examples, fields, vocab_path=self.vocab_path, tokenize_columns=header
        )

        return corpus

    @staticmethod
    def item_to_example(
        item: RawItem, fields: List[Tuple[str, Field]], verb_inflections: Dict[str, str]
    ) -> Optional[Example]:
        """ Creates an Example containing the subsentence and both
        forms of the verb. If a verb form is not present in the model
        vocab, None is returned.
        """
        orig_sentence = item.orig_sentence

        if not all(ord(c) < 256 for c in orig_sentence):
            orig_sentence = unidecode(orig_sentence)

        subsen = orig_sentence.split()[: int(item.verb_index) - 1]
        opposite_verb = verb_inflections.get(item.verb, None)

        if opposite_verb is None:
            return None

        return Example.fromlist([subsen, item.verb, opposite_verb], fields)

    def create_verb_inflections(self, corpus_path: str) -> Dict[str, str]:
        """ Create sing<>plur mappings for all verbs in the model vocab.

        Mappings are based on the pos-tagged wiki.vocab file of Linzen
        et al., and the `inflect` library.

        We only add token mappings if both the singular and plural form
        is present in the model's vocabulary.
        """
        infl_eng = inflect.engine()

        with open(self.vocab_path) as f:
            model_vocab = set(line.strip() for line in f)

        pos_to_token = {"VBP": [], "VBZ": []}

        try:
            with open(os.path.join(corpus_path, "wiki.vocab")) as file:
                next(file)
                for line in file:
                    word, pos, _ = line.strip().split()
                    if word in model_vocab and pos in pos_to_token:
                        pos_to_token[pos].append(word)
        except FileNotFoundError:
            warnings.warn(
                "wiki.vocab is expected to be located in the same directory as the full corpus."
            )
            raise

        verb_inflections = {}
        for word in pos_to_token["VBZ"]:
            candidate = infl_eng.plural_verb(word)
            if candidate in pos_to_token["VBP"]:
                verb_inflections[candidate] = word
                verb_inflections[word] = candidate

        return verb_inflections
