# conversions as been done by StanfordConverter (a.k.a SC) version TODO
# global nuances from their converter:
#   1. we always write to 'deps' (so at first we copy 'head'+'deprel' to 'deps'), while they sometimes write back to 'deprel'.
#   2. we think like a multi-graph, so we operate on every relation/edge between two nodes, while they on first one found.
#   3. we look for all fathers as we can have multiple fathers, while in SC they look at first one found.

import sys
from collections import defaultdict
import inspect

from .constraints import *
from .graph_token import Label, TokenId
from .matcher import Matcher, NamedConstraint
from dataclasses import dataclass
from .conllu_wrapper import serialize_conllu

# constants   # TODO - english specific
clause_relations = ["conj", "xcomp", "ccomp", "acl", "advcl", "acl:relcl", "parataxis", "appos", "list"]
quant_mod_3w = ['lot', 'assortment', 'number', 'couple', 'bunch', 'handful', 'litany', 'sheaf', 'slew', 'dozen', 'series', 'variety', 'multitude', 'wad', 'clutch', 'wave', 'mountain', 'array', 'spate', 'string', 'ton', 'range', 'plethora', 'heap', 'sort', 'form', 'kind', 'type', 'version', 'bit', 'pair', 'triple', 'total']
quant_mod_2w = ['lots', 'many', 'several', 'plenty', 'tons', 'dozens', 'multitudes', 'mountains', 'loads', 'pairs', 'tens', 'hundreds', 'thousands', 'millions', 'billions', 'trillions']
quant_mod_2w_det = ['some', 'all', 'both', 'neither', 'everyone', 'nobody', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'hundred', 'thousand', 'million', 'billion', 'trillion']
relativizing_words = ["that", "what", "which", "who", "whom", "whose"]
relativizers_to_rel = {'where': "nmod:lmod", "how": "nmod", "when": "nmod:tmod", "why": "nmod"}
neg_conjp_prev = ["if_not"]
neg_conjp_next = ["instead_of", "rather_than", "but_rather", "but_not"]
and_conjp_next = ["as_well", "but_also"]
advmod_list = ['here', 'there', 'now', 'later', 'soon', 'before', 'then', 'today', 'tomorrow', 'yesterday', 'tonight', 'earlier', 'early']
evidential_list = ['seem', 'appear', 'be', 'sound']
aspectual_list = ['begin', 'continue', 'delay', 'discontinue', 'finish', 'postpone', 'quit', 'resume', 'start', 'complete']
reported_list = ['report', 'say', 'declare', 'announce', 'tell', 'state', 'mention', 'proclaim', 'replay', 'point', 'inform', 'explain', 'clarify', 'define', 'expound', 'describe', 'illustrate', 'justify', 'demonstrate', 'interpret', 'elucidate', 'reveal', 'confess', 'admit', 'accept', 'affirm', 'swear', 'agree', 'recognise', 'testify', 'assert', 'think', 'claim', 'allege', 'argue', 'assume', 'feel', 'guess', 'imagine', 'presume', 'suggest', 'argue', 'boast', 'contest', 'deny', 'refute', 'dispute', 'defend', 'warn', 'maintain', 'contradict']
advcl_non_legit_markers = ["as", "so", "when", "if"]  # TODO - english specific
adj_pos = ["JJ", "JJR", "JJS"]
verb_pos = ["VB", "VBD", "VBG", "VBN", "VBP", "VBZ", "MD"]
noun_pos = ["NN", "NNS", "NNP", "NNPS"]
pron_pos = ["PRP", "PRP$", "WP", "WP$"]
udv_map = {"nsubjpass": "nsubj:pass", "csubjpass": "csubj:pass", "auxpass": "aux:pass", "dobj": "obj", "mwe": "fixed",
           "nmod": "obl", "nmod:agent": "obl:agent", "nmod:tmod": "obl:tmod", "nmod:lmod": "obl:lmod"}


class ConvTypes(Enum):
    EUD = 1
    EUDPP = 2
    BART = 3


ConvFuncSignature = Callable[[Any, Any, Any], None]


@dataclass
class Conversion:
    conv_type: ConvTypes
    constraint: Full
    transformation: ConvFuncSignature

    def __post_init__(self):
        self.name = self.transformation.__name__


def get_eud_info(eud_str, converter):
    return eud_str if not converter.remove_enhanced_extra_info else None


def get_conversion_names():
    return {func_name for (func_name, _) in inspect.getmembers(sys.modules[__name__], inspect.isfunction)
            if (func_name.startswith("eud") or func_name.startswith("eudpp") or func_name.startswith("extra"))}


def create_mwe(words, head, rel, secondary_rel, converter):
    for i, word in enumerate(words):
        word.remove_all_edges()
        word.add_edge(rel, head)
        if 0 == i:
            head = word
            rel = Label(secondary_rel)


def reattach_children(old_head, new_head, new_rel=None, cond=None):
    [child.replace_edge(child_rel, new_rel if new_rel else child_rel, old_head, new_head) for
     (child, child_rels) in old_head.get_children_with_rels() for child_rel in child_rels if not cond or cond(child_rel)]


def reattach_parents(old_child, new_child, new_rel=None, rel_by_cond=lambda x, y, z: x if x else y):
    new_child.remove_all_edges()
    [(old_child.remove_edge(parent_rel, head), new_child.add_edge(rel_by_cond(new_rel, parent_rel, head), head))
     for (head, parent_rels) in list(old_child.get_new_relations()) for parent_rel in parent_rels]


# TODO: english = this entire function
# resolves the following multi word conj phrases:
#   a. 'but(cc) not', 'if not', 'instead of', 'rather than', 'but(cc) rather'. GO TO negcc
#   b. 'as(cc) well as', 'but(cc) also', 'not to mention', '&'. GO TO and
# NOTE: This is bad practice (and sometimes not successful neither for SC or for us) for the following reasons:
#   1. Not all parsers mark the same words as cc (if at all), so looking for the cc on a specific word is wrong.
#       as of this reason, for now we and SC both miss: if-not, not-to-mention
#   2. Some of the multi-words are already treated as multi-word prepositions (and are henceforth missed):
#       as of this reason, for now we and SC both miss: instead-of, rather-than
def get_assignment(sentence, cc):
    cc_cur_id = cc.get_conllu_field('id').major - 1
    prev_forms = "_".join([info.get_conllu_field('form') for (iid, info) in enumerate(sentence)
                           if (cc_cur_id - 1 == iid or cc_cur_id == iid)])
    next_forms = "_".join([info.get_conllu_field('form') for (iid, info) in enumerate(sentence)
                           if (cc_cur_id + 1 == iid) or (cc_cur_id == iid)])
    if next_forms in neg_conjp_next or prev_forms in neg_conjp_prev:
        return "negcc"
    elif (next_forms in and_conjp_next) or (cc.get_conllu_field('form') == '&'):
        return ""  # 中文默认顿号，即什么都不返回
    else:
        return cc.get_conllu_field('form')


# In case multiple coordination marker depend on the same governor
# the one that precedes the conjunct is appended to the conjunction relation or the
# first one if no preceding marker exists.
def assign_ccs_to_conjs(sentence, cc_assignments):
    for token in sentence:
        ccs = []
        for child, rels in sorted(token.get_children_with_rels(), reverse=True):
            for rel in rels:
                if 'cc' == rel.base:
                    ccs.append(child)
        i = 0
        for child, rels in sorted(token.get_children_with_rels(), reverse=True):
            for rel in rels:
                if rel.base.startswith('conj'):
                    if len(ccs) != 0:       #==0为、的情况
                        cc = ccs[i if i < len(ccs) else -1]
                        cc_assignments[child] = (cc, get_assignment(sentence, cc))
                    i += 1


# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++ #


def init_conversions(remove_node_adding_conversions, ud_version):

    def word_propagation(sentence, matches, converter):
        for cur_match in matches:
            gov = cur_match.token("gov")
            prop = cur_match.token("prop")
            conj = cur_match.token("conj")
            if sentence[conj].get_conllu_field("deprel") != "root":
                sentence[prop].add_edge(Label(sentence[conj].get_conllu_field("deprel")), sentence[gov])

    #并列主语
    word_nsubj_propagation_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="conj"),
        ],
        edges=[
            Edge(child="prop", parent="conj", label=[HasLabelFromList(["conj"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["nsubj"])]),
        ],
    )

    def word_nsubj_propagation(sentence, matches, converter):
        for cur_match in matches:
            gov = cur_match.token("gov")
            prop = cur_match.token("prop")
            conj = cur_match.token("conj")
            min_id = min(prop, conj, gov)
            max_id = max(prop, conj, gov)
            is_sen = 0
            for i in range(min_id, max_id + 1):
                if sentence[i].get_conllu_field("form") == "，":
                    is_sen = 1
                    break
            if is_sen == 0:
                sentence[prop].add_edge(Label("nsubj"), sentence[gov])
    #并列宾语
    word_dobj_propagation_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="conj"),
        ],
        edges=[
            Edge(child="prop", parent="conj", label=[HasLabelFromList(["conj"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["dobj"])]),
        ],
    )

    def word_dobj_propagation(sentence, matches, converter):
        for cur_match in matches:
            gov = cur_match.token("gov")
            prop = cur_match.token("prop")
            conj = cur_match.token("conj")
            min_id = min(prop, conj, gov)
            max_id = max(prop, conj, gov)
            is_sen = 0
            for i in range(min_id, max_id + 1):
                if sentence[i].get_conllu_field("form") == "，":
                    is_sen = 1
                    break
            if is_sen == 0:
                sentence[prop].add_edge(Label("dobj"), sentence[gov])

    #并列修饰语：修饰名词（修饰词为名词）
    word_nmod_compoundnn_propagation_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="conj"),
        ],
        edges=[
            Edge(child="prop", parent="conj", label=[HasLabelFromList(["conj"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["nmod:assmod"])]),
        ],
    )

    def word_nmod_compoundnn_propagation(sentence, matches, converter):
        word_propagation(sentence, matches, converter)

    #传播时间、地点、范围状语等
    word_nmod_tmod_propagation_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="conj"),
        ],
        edges=[
            Edge(child="prop", parent="conj", label=[HasLabelFromList(["conj"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["nmod:tmod"])]),
        ],
    )

    def word_nmod_tmod_propagation(sentence, matches, converter):
        word_propagation(sentence, matches, converter)


    #并列修饰语：修饰名词（修饰词为形容词）
    word_amod_propagation_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="conj"),
        ],
        edges=[
            Edge(child="prop", parent="conj", label=[HasLabelFromList(["conj"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["amod"])]),
        ],
    )

    def word_amod_propagation(sentence, matches, converter):
        word_propagation(sentence, matches, converter)

    #并列修饰语：动词短语作定语修饰中心语
    word_acl_propagation_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="conj"),
        ],
        edges=[
            Edge(child="prop", parent="conj", label=[HasLabelFromList(["conj"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["acl"])]),
        ],
    )

    def word_acl_propagation(sentence, matches, converter):
        word_propagation(sentence, matches, converter)

    # 并列谓语：传播主语+连动句
    predicate_nsubj_propagation_constraint = Full(
        tokens=[
            Token(id="gov", outgoing_edges=[HasNoLabel("cop")]),
            Token(id="prop"),
            Token(id="conj"),
        ],
        edges=[
            Edge(child="prop", parent="gov", label=[HasLabelFromList(["nsubj"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["conj"])]),
        ],
    )

    def predicate_nsubj_propagation(sentence, matches, converter):
        for cur_match in matches:
            gov = cur_match.token("gov")
            prop = cur_match.token("prop")
            conj = cur_match.token("conj")
            is_prop = len([child for child in sentence[conj].get_children() if child.get_conllu_field("deprel") in ["nsubj"]])
            min_id = min(prop, conj, gov)
            max_id = max(prop, conj, gov)
            is_sen = 0
            for i in range(min_id, max_id + 1):
                if sentence[i].get_conllu_field("form") == "，":
                    is_sen = 1
                    break
            if is_prop == 0 and is_sen == 0:
                sentence[prop].add_edge(Label("nsubj"), sentence[conj])

    # 并列谓语：传播宾语
    predicate_dobj_propagation_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="conj"),
        ],
        edges=[
            Edge(child="prop", parent="conj", label=[HasLabelFromList(["dobj"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["conj"])]),
        ],
    )

    def predicate_dobj_propagation(sentence, matches, converter):
        for cur_match in matches:
            gov = cur_match.token("gov")
            prop = cur_match.token("prop")
            conj = cur_match.token("conj")
            gov_child = sentence[gov].get_children()
            conj_child = sentence[conj].get_children()
            is_advmod = 1
            if len([child for child in gov_child if child.get_conllu_field("form") == "一" and child.get_conllu_field("deprel") =="advmod"]) and len([child for child in conj_child if child.get_conllu_field("form") == "就" and child.get_conllu_field("deprel") =="advmod"]):
                is_advmod = 0
            is_prop= len([child for child in conj_child if child.get_conllu_field("deprel") == "nsubj"]) + len([child for child in gov_child if child.get_conllu_field("deprel") == "dobj"])
            min_id = min(prop, gov)
            max_id = max(prop, gov)
            is_sen = 0
            for i in range(min_id, max_id + 1):
                if sentence[i].get_conllu_field("form") == "，":
                    is_sen = 1
                    break
            if is_prop == 0 and is_advmod and is_sen == 0:
                sentence[prop].add_edge(Label("dobj"), sentence[gov])

    def predicate_x_propagation(sentence, matches, converter):
        for cur_match in matches:
            prop = cur_match.token("prop")
            conj = cur_match.token("conj")
            if sentence[prop].get_conllu_field("deprel") not in [child.get_conllu_field("deprel") for child in sentence[conj].get_children()]:
                sentence[prop].add_edge(Label(sentence[prop].get_conllu_field("deprel")), sentence[conj])

    # 并列谓语：传播状语（时间、地点）
    predicate_loc_propagation_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="conj"),
        ],
        edges=[
            Edge(child="prop", parent="gov", label=[HasLabelFromList(["advmod:loc", "advcl:loc", "nmod:tmod"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["conj"])]),
        ],
    )

    def predicate_loc_propagation(sentence, matches, converter):
        predicate_x_propagation(sentence, matches, converter)

    # 并列中心语：传播修饰词
    modified_propagation_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="conj"),
        ],
        edges=[
            Edge(child="prop", parent="gov", label=[HasLabelFromList(["amod", "nmod:assmod", "acl"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["conj"])]),
        ],
    )

    def modified_propagation(sentence, matches, converter):
        for cur_match in matches:
            gov = cur_match.token("gov")
            prop = cur_match.token("prop")
            conj = cur_match.token("conj")
            if sentence[gov].get_conllu_field("id") > sentence[conj].get_conllu_field("id") and sentence[conj].get_conllu_field("id") > sentence[prop].get_conllu_field("id"):
                if sentence[prop].get_conllu_field("deprel") not in [child.get_conllu_field("deprel") for child in sentence[conj].get_children()]:
                    sentence[prop].add_edge(Label(sentence[prop].get_conllu_field("deprel")), sentence[conj])

    advmod_propagation_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="conj"),
        ],
        edges=[
            Edge(child="prop", parent="gov", label=[HasLabelFromList(["advmod", "advmod:dvp"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["conj"])]),
        ],
    )

    def advmod_propagation(sentence, matches, converter):
        for cur_match in matches:
            gov = cur_match.token("gov")
            prop = cur_match.token("prop")
            conj = cur_match.token("conj")
            max_id = max(gov, conj)
            min_id = min(gov, conj)
            is_sen = 1
            for i in range(min_id, max_id + 1):
                if sentence[i].get_conllu_field("form") == "，":
                    is_sen = 0
                    break
            if is_sen:
                if sentence[prop].get_conllu_field("deprel") not in [child.get_conllu_field("deprel") for child in sentence[conj].get_children()]:
                    sentence[prop].add_edge(Label(sentence[prop].get_conllu_field("deprel")), sentence[conj])

    # 并列动词短语：传播介宾短语作状语
    nmod_prep_propagation_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="conj"),
        ],
        edges=[
            Edge(child="prop", parent="gov", label=[HasLabelFromList(["nmod:prep"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["conj"])]),
        ],
    )

    def nmod_prep_propagation(sentence, matches, converter):
        for cur_match in matches:
            gov = cur_match.token("gov")
            prop = cur_match.token("prop")
            conj = cur_match.token("conj")
            max_id = max(gov, conj)
            min_id = min(gov,conj)
            is_sen = 1
            for i in range(min_id, max_id + 1):
                if sentence[i].get_conllu_field("form") == "，":
                    is_sen = 0
                    break
            if is_sen and gov < conj:
                if sentence[prop].get_conllu_field("deprel") not in [child.get_conllu_field("deprel") for child in sentence[conj].get_children()]:
                    sentence[prop].add_edge(Label(sentence[prop].get_conllu_field("deprel")), sentence[conj])

    # 传播介词
    case_propagation_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="conj"),
        ],
        edges=[
            Edge(child="prop", parent="gov", label=[HasLabelFromList(["case"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["conj"])]),
        ],
    )

    def case_propagation(sentence, matches, converter):
        predicate_x_propagation(sentence, matches, converter)

    # 并列修饰语：修饰动词
    verb_advmod_propagation_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="conj"),
        ],
        edges=[
            Edge(child="prop", parent="conj", label=[HasLabelFromList(["conj"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["advmod", "advmod:dvp"])]),
        ],
    )

    def verb_advmod_propagation(sentence, matches, converter):
        for cur_match in matches:
            gov = cur_match.token("gov")
            prop = cur_match.token("prop")
            conj = cur_match.token("conj")
            gov_child = sentence[gov].get_children()
            conj_child = sentence[conj].get_children()
            is_advmod = 1
            if len([child for child in gov_child if child.get_conllu_field("form") == "一" and child.get_conllu_field("deprel") =="advmod"]) and len([child for child in conj_child if child.get_conllu_field("form") == "就" and child.get_conllu_field("deprel") =="advmod"]):
                is_advmod = 0
            if is_advmod:
                sentence[prop].add_edge(Label(sentence[conj].get_conllu_field("deprel")), sentence[gov])

    # 传播助词
    aux_propagation_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="conj"),
        ],
        edges=[
            Edge(child="prop", parent="gov", label=[HasLabelFromList(["aux:modal", "aux:prtmod", "auxpass"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["conj"])]),
        ],
    )

    def aux_propagation(sentence, matches, converter):
        for cur_match in matches:
            prop = cur_match.token("prop")
            conj = cur_match.token("conj")
            is_aux = len([child for child in sentence[conj].get_children() if child.get_conllu_field("deprel") == sentence[prop].get_conllu_field("deprel")])
            if is_aux == 0:
                sentence[prop].add_edge(Label(sentence[prop].get_conllu_field("deprel")), sentence[conj])

    #同位语
    extra_appos_propagation_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="appos"),
            Token(id="gov_parent", optional=True),
            Token(id="gov_son", optional=True),
        ],
        edges=[
            Edge(child="gov", parent="gov_parent", label=[HasLabelFromList(["nsubj", "compound:nn", "nmod:prep", "conj", "nmod:assmod", "dobj"])]),
            Edge(child="gov_son", parent="gov", label=[HasLabelFromList(["acl", "amod"])]),
            Edge(child="appos", parent="gov", label=[HasLabelFromList(["appos"])]),
        ],
    )

    def extra_appos_propagation(sentence, matches, converter):
        for cur_match in matches:
            gov_parent = cur_match.token("gov_parent")
            gov_son = cur_match.token("gov_son")
            gov = cur_match.token("gov")
            appos = cur_match.token("appos")
            for label in cur_match.edge(gov, gov_parent):
                sentence[appos].add_edge(Label(label), sentence[gov_parent])
            for label in cur_match.edge(gov_son, gov):
                sentence[gov_son].add_edge(Label(label), sentence[appos])

    # 复合词：动词复合词
    compoundvc_propagation_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="gov_son", optional=True),
            Token(id="gov_parent", optional=True),
            Token(id="com_vc"),
        ],
        edges=[
            Edge(child="gov_son", parent="gov", label=[HasLabelFromList(["advmod", "advmod:loc", "advcl:loc", "nmod:prep", "nsubj", "dobj"])]),
            Edge(child="gov", parent="gov_parent", label=[HasLabelFromList(["advmod:dvp"])]),
            Edge(child="com_vc", parent="gov", label=[HasLabelFromList(["compound:vc"])]),
        ],
    )

    def compoundvc_propagation(sentence, matches, converter):
        for cur_match in matches:
            gov_parent = cur_match.token("gov_parent")
            gov_son = cur_match.token("gov_son")
            gov = cur_match.token("gov")
            com_vc = cur_match.token("com_vc")
            for label in cur_match.edge(gov, gov_parent):
                sentence[com_vc].add_edge(Label(label), sentence[gov_parent])
            for label in cur_match.edge(gov_son, gov):
                sentence[gov_son].add_edge(Label(label), sentence[com_vc])

    # 被动句
    passivization_alternation_constraint = Full(
        tokens=[
            Token(id="gov", spec=[Field(FieldNames.TAG, ["VV"])]),
            Token(id="gov_child", optional=True),
            Token(id="gov_parent", optional=True),
            Token(id="pass", spec=[Field(FieldNames.WORD, ["被"])]),
            Token(id="gov_nsubj", optional=True),
            Token(id="gov_mark", optional=True),
        ],
        edges=[
            Edge(child="gov_child", parent="gov", label=[HasLabelFromList(["nsubjpass"])]),
            Edge(child="gov", parent="gov_parent", label=[HasLabelFromList(["acl"])]),
            Edge(child="pass", parent="gov", label=[HasLabelFromList(["auxpass"])]),
            Edge(child="gov_nsubj", parent="gov", label=[HasLabelFromList(["nsubj"])]),
            Edge(child="gov_mark", parent="gov", label=[HasLabelFromList(["mark"])]),
        ],
    )

    def passivization_alternation(sentence, matches, converter):
        for cur_match in matches:
            gov_parent = cur_match.token("gov_parent")
            gov_child = cur_match.token("gov_child")
            gov = cur_match.token("gov")
            for label in cur_match.edge(gov, gov_parent):
                is_prop = len([child for child in sentence[gov].get_children() if child.get_conllu_field("deprel") in ["nsubjpass"]])
                if is_prop == 0:
                    sentence[gov_parent].add_edge(Label("dobj"), sentence[gov])
            for label in cur_match.edge(gov_child, gov):
                sentence[gov_child].add_edge(Label("dobj"), sentence[gov])

    #把字句
    aux_ba_alternative_constraint = Full(
        tokens=[
            Token(id="gov", spec=[Field(field=FieldNames.TAG, value=["VV"])]),
            Token(id="aux_ba", spec=[Field(FieldNames.WORD, ["把"])], outgoing_edges=[HasNoLabel("dobj")]),
            Token(id="dep"),
        ],
        edges=[
            Edge(child="aux_ba", parent="gov", label=[HasLabelFromList(["aux:ba"])]),
            Edge(child="dep", parent="gov", label=[HasLabelFromList(["dep"])]),
        ],
    )

    def aux_ba_alternative(sentence, matches, converter):
        for cur_match in matches:
            gov = cur_match.token("gov")
            dep = cur_match.token("dep")
            aux_ba = cur_match.token("aux_ba")
            if aux_ba < dep and dep < gov:
                sentence[dep].add_edge(Label("dobj"), sentence[gov])

    #amod形容词修饰词和主谓间的转换
    amod_alternative_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="amod", spec=[Field(field=FieldNames.TAG, value=["VA"])]),
        ],
        edges=[
            Edge(child="amod", parent="gov", label=[HasLabelFromList(["amod"])]),
        ],
    )

    def amod_alternative(sentence, matches, converter):
        for cur_match in matches:
            gov = cur_match.token("gov")
            amod = cur_match.token("amod")
            is_prop = len([child for child in sentence[amod].get_children() if child.get_conllu_field("deprel") in ["nsubj"]])
            if is_prop == 0:
                sentence[gov].add_edge(Label("nsubj"), sentence[amod])

    #acl_a
    acl_nsubj_alternative_constraint = Full(
        tokens=[
            Token(id="gov", outgoing_edges=[HasNoLabel("auxpass")]),
            Token(id="gov_acl"),
            Token(id="dobj"),
            Token(id="mark", spec=[Field(FieldNames.WORD, ["的"])]),
        ],
        edges=[
            Edge(child="gov", parent="gov_acl", label=[HasLabelFromList(["acl"])]),
            Edge(child="mark", parent="gov", label=[HasLabelFromList(["mark"])]),
            Edge(child="dobj", parent="gov", label=[HasLabelFromList(["dobj"])]),
        ],
    )

    def acl_nsubj_alternative(sentence, matches, converter):
        for cur_match in matches:
            gov = cur_match.token("gov")
            gov_acl = cur_match.token("gov_acl")
            is_gov_acl_nsubj = len([child for child in sentence[gov].get_children() if child.get_conllu_field("deprel") == "nsubj"])
            if is_gov_acl_nsubj == 0:
                sentence[gov_acl].add_edge(Label("nsubj(UNC)"), sentence[gov])

    #acl_b
    acl_dobj_alternative_constraint = Full(
        tokens=[
            Token(id="gov", outgoing_edges=[HasNoLabel("auxpass")], spec=[Field(field=FieldNames.TAG, value=["VV"])]),
            Token(id="gov_acl"),
            Token(id="nsubj"),
            Token(id="mark", spec=[Field(FieldNames.WORD, ["的"])]),
        ],
        edges=[
            Edge(child="gov", parent="gov_acl", label=[HasLabelFromList(["acl"])]),
            Edge(child="mark", parent="gov", label=[HasLabelFromList(["mark"])]),
            Edge(child="nsubj", parent="gov", label=[HasLabelFromList(["nsubj"])]),
        ],
    )

    def acl_dobj_alternative(sentence, matches, converter):
        for cur_match in matches:
            gov = cur_match.token("gov")
            gov_acl = cur_match.token("gov_acl")
            is_gov_acl_dobj = len([child for child in sentence[gov].get_children() if child.get_conllu_field("deprel") == "dobj"])
            if is_gov_acl_dobj == 0:
                sentence[gov_acl].add_edge(Label("dobj(UNC)"), sentence[gov])

    # 兼语句
    ccomp_propagation_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="ccomp"),
            Token(id="cop", optional=True),
        ],
        edges=[
            Edge(child="prop", parent="gov", label=[HasLabelFromList(["dobj"])]),
            Edge(child="ccomp", parent="gov", label=[HasLabelFromList(["ccomp"])]),
            Edge(child="cop", parent="ccomp", label=[HasLabelFromList(["cop"])]),
        ],
    )

    def ccomp_propagation(sentence, matches, converter):
        for cur_match in matches:
            gov = cur_match.token("gov")
            prop = cur_match.token("prop")
            ccomp = cur_match.token("ccomp")
            cop = cur_match.token("cop")

            if cop != -1:
                max_id = max(gov, prop, ccomp, cop)
                min_id = min(gov, prop, ccomp, cop)
                is_sen = 1
                for i in range(min_id, max_id + 1):
                    if sentence[i].get_conllu_field("upos") == "PU":
                        is_sen = 0
                        break
                if is_sen and sentence[prop].get_conllu_field("id") < sentence[cop].get_conllu_field("id"):
                    sentence[prop].add_edge(Label("nsubj"), sentence[cop])
            else:
                max_id = max(gov, prop, ccomp)
                min_id = min(gov, prop, ccomp)
                is_sen = 1
                for i in range(min_id, max_id + 1):
                    if sentence[i].get_conllu_field("upos") == "PU":
                        is_sen = 0
                        break
                if is_sen and sentence[prop].get_conllu_field("id") < sentence[ccomp].get_conllu_field("id"):
                    sentence[prop].add_edge(Label("nsubj"), sentence[ccomp])

    #状语从句
    adverbial_clause_propagation_1_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="adv"),
        ],
        edges=[
            Edge(child="prop", parent="gov", label=[HasLabelFromList(["nsubj"])]),
            Edge(child="adv", parent="gov", label=[HasLabelFromList(["advcl:loc"])]),
        ],
    )

    def adverbial_clause_propagation_1(sentence, matches, converter):
        for cur_match in matches:
            prop = cur_match.token("prop")
            adv = cur_match.token("adv")
            is_adv_nsubj = len([child for child in sentence[adv].get_children() if child.get_conllu_field("deprel") == "nsubj"])
            if is_adv_nsubj == 0:
                sentence[prop].add_edge(Label("nsubj(UNC)", uncertain = True), sentence[adv])

    adverbial_clause_propagation_2_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="adv"),
        ],
        edges=[
            Edge(child="prop", parent="adv", label=[HasLabelFromList(["nsubj"])]),
            Edge(child="adv", parent="gov", label=[HasLabelFromList(["advcl:loc"])]),
        ],
    )

    def adverbial_clause_propagation_2(sentence, matches, converter):
        for cur_match in matches:
            prop = cur_match.token("prop")
            gov = cur_match.token("gov")
            is_gov_nsubj = len([child for child in sentence[gov].get_children() if child.get_conllu_field("deprel") == "nsubj"])
            if is_gov_nsubj == 0:
                sentence[prop].add_edge(Label("nsubj(UNC)", uncertain=True), sentence[gov])

    #复句
    complex_sentences_propagation_1_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="conj"),
            Token(id="punct", spec=[Field(field=FieldNames.WORD, value=["，"])]),
        ],
        edges=[
            Edge(child="punct", parent="gov", label=[HasLabelFromList(["punct"])]),
            Edge(child="prop", parent="gov", label=[HasLabelFromList(["nsubj"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["conj"])]),
        ],
    )

    def complex_sentences_propagation_1(sentence, matches, converter):
        for cur_match in matches:
            prop = cur_match.token("prop")
            conj = cur_match.token("conj")
            punct = cur_match.token("punct")
            is_conj_nsubj = len([child for child in sentence[conj].get_children() if child.get_conllu_field("deprel") == "nsubj"])
            max_id = max(sentence[conj].get_conllu_field("id"), sentence[prop].get_conllu_field("id"))
            min_id = min(sentence[conj].get_conllu_field("id"), sentence[prop].get_conllu_field("id"))
            if is_conj_nsubj == 0 and sentence[punct].get_conllu_field("id") < max_id and sentence[punct].get_conllu_field("id") > min_id:
                sentence[prop].add_edge(Label("nsubj(UNC)", uncertain=True), sentence[conj])

    complex_sentences_propagation_2_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="prop"),
            Token(id="conj"),
            Token(id="punct", spec=[Field(field=FieldNames.WORD, value=["，"])]),
        ],
        edges=[
            Edge(child="punct", parent="gov", label=[HasLabelFromList(["punct"])]),
            Edge(child="prop", parent="conj", label=[HasLabelFromList(["nsubj"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["conj"])]),
        ],
    )

    def complex_sentences_propagation_2(sentence, matches, converter):
        for cur_match in matches:
            prop = cur_match.token("prop")
            gov = cur_match.token("gov")
            conj = cur_match.token("conj")
            punct = cur_match.token("punct")
            is_gov_nsubj = len([child for child in sentence[gov].get_children() if child.get_conllu_field("deprel") == "nsubj"])
            max_id = max(sentence[conj].get_conllu_field("id"), sentence[prop].get_conllu_field("id"))
            min_id = min(sentence[conj].get_conllu_field("id"), sentence[prop].get_conllu_field("id"))
            if is_gov_nsubj == 0 and sentence[punct].get_conllu_field("id") < max_id and sentence[punct].get_conllu_field("id") > min_id:
                sentence[prop].add_edge(Label("nsubj(UNC)", uncertain=True), sentence[gov])

    #省略主语
    omit_nsubj_propagation_constraint = Full(
        tokens=[
            Token(id="gov", spec=[Field(field=FieldNames.TAG, value=["VV", "VE", "VC"])]),
            Token(id="prop"),
            Token(id="conj", spec=[Field(field=FieldNames.TAG, value=["VV", "VE", "VC"])], outgoing_edges=[HasNoLabel(child) for child in ["ccomp", "nmod:range"]]),
            Token(id="punct", spec=[Field(field=FieldNames.WORD, value=["，"])]),
            Token(id="dobj", optional=True),
        ],
        edges=[
            Edge(child="punct", parent="gov", label=[HasLabelFromList(["punct"])]),
            Edge(child="prop", parent="gov", label=[HasLabelFromList(["nsubj"])]),
            Edge(child="dobj", parent="gov", label=[HasLabelFromList(["dobj"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["/.*/"])]),
        ],
    )

    def omit_nsubj_propagation(sentence, matches, converter):
        for cur_match in matches:
            prop = cur_match.token("prop")
            gov = cur_match.token("gov")
            conj = cur_match.token("conj")
            dobj = cur_match.token("dobj")
            punct = cur_match.token("punct")
            is_conj_nsubj = len([child for child in sentence[conj].get_children() if child.get_conllu_field("deprel") == "nsubj"])
            conj_id = sentence[conj].get_conllu_field("id")
            prop_id = sentence[prop].get_conllu_field("id")
            gov_id = sentence[gov].get_conllu_field("id")
            punct_id = sentence[punct].get_conllu_field("id")
            if (conj_id < punct_id and prop_id > punct_id and gov_id > punct_id) or (conj_id > punct_id and prop_id < punct_id and gov_id < punct_id):
                is_diff_sen = 1
            else:
                is_diff_sen = 0
            count = 0
            max_id = max(gov, prop, conj, dobj)
            min_id = min(gov, prop, conj, dobj)
            for i in range(min_id, max_id + 1):
                if sentence[i].get_conllu_field("form") == "，":
                    count += 1
            is_conj = 0
            if count == 1 or (count > 1 and sentence[conj].get_conllu_field("deprel") == "conj"):
                is_conj = 1

            cur_iid = conj
            if is_conj_nsubj == 0 and is_diff_sen and is_conj:
                if dobj != -1:
                    sentence[prop].add_edge(Label("nsubj(ALT=" + str(cur_iid + 1) + ")", iid=cur_iid , uncertain=True), sentence[conj])
                    sentence[dobj].add_edge(Label("nsubj(ALT=" + str(cur_iid + 1) + ")", iid=cur_iid , uncertain=True), sentence[conj])
                else:
                    sentence[prop].add_edge(Label("nsubj(UNC)", uncertain=True), sentence[conj])

    #省略宾语
    omit_dobj_propagation_constraint = Full(
        tokens=[
            Token(id="gov", spec=[Field(field=FieldNames.TAG, value=["VV", "VE", "VC"])]),
            Token(id="prop"),
            Token(id="conj", spec=[Field(field=FieldNames.TAG, value=["VV", "VE", "VC"])], outgoing_edges=[HasNoLabel(child) for child in ["ccomp", "nmod:range"]]),
            Token(id="punct", spec=[Field(field=FieldNames.WORD, value=["，"])]),
            Token(id="nsubj", optional=True),
        ],
        edges=[
            Edge(child="punct", parent="gov", label=[HasLabelFromList(["punct"])]),
            Edge(child="prop", parent="gov", label=[HasLabelFromList(["dobj"])]),
            Edge(child="nsubj", parent="gov", label=[HasLabelFromList(["nsubj"])]),
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["/.*/"])]),
        ],
    )

    def omit_dobj_propagation(sentence, matches, converter):
        for cur_match in matches:
            prop = cur_match.token("prop")
            gov = cur_match.token("gov")
            conj = cur_match.token("conj")
            nsubj = cur_match.token("nsubj")
            punct = cur_match.token("punct")
            is_conj_dobj = len([child for child in sentence[conj].get_children() if child.get_conllu_field("deprel") == "dobj"])
            conj_id = sentence[conj].get_conllu_field("id")
            prop_id = sentence[prop].get_conllu_field("id")
            gov_id = sentence[gov].get_conllu_field("id")
            punct_id = sentence[punct].get_conllu_field("id")
            if (conj_id < punct_id and prop_id > punct_id and gov_id > punct_id) or (conj_id > punct_id and prop_id < punct_id and gov_id < punct_id):
                is_diff_sen = 1
            else:
                is_diff_sen = 0
            count = 0
            max_id = max(gov, prop, conj, nsubj)
            min_id = min(gov, prop, conj, nsubj)
            for i in range(min_id, max_id + 1):
                if sentence[i].get_conllu_field("form") == "，":
                    count += 1
            is_conj = 0
            if count == 1 or (count > 1 and sentence[conj].get_conllu_field("deprel") == "conj"):
                is_conj = 1

            cur_iid = conj
            if is_conj_dobj == 0 and is_diff_sen and is_conj:
                if nsubj != -1:
                    sentence[prop].add_edge(Label("dobj(ALT=" + str(cur_iid + 1) + ")", iid=cur_iid , uncertain=True), sentence[conj])
                    sentence[nsubj].add_edge(Label("dobj(ALT=" + str(cur_iid + 1) + ")", iid=cur_iid , uncertain=True), sentence[conj])
                else:
                    sentence[prop].add_edge(Label("dobj(UNC)", uncertain=True), sentence[conj])

    #介词加强
    def prep_strength_1(sentence, matches, converter):
        for cur_match in matches:
            gov = cur_match.token("gov")
            prep = cur_match.token("prep")
            case = cur_match.token("case")
            case_num = len([child for child in sentence[prep].get_children() if child.get_conllu_field("deprel") == "case"])
            if case_num == 1:
                for label in cur_match.edge(prep, gov):
                    sentence[prep].replace_edge(Label(label), Label(label + "_" + sentence[case].get_conllu_field("form")), sentence[gov], sentence[gov])

    nmod_prep_1_strengthen_constraint = Full(
        tokens=[
            Token(id="prep"),
            Token(id="gov"),
            Token(id="case"),
        ],
        edges=[
            Edge(child="case", parent="prep", label=[HasLabelFromList(["case"])]),
            Edge(child="prep", parent="gov", label=[HasLabelFromList(["nmod:prep"])]),
        ],
    )

    def nmod_prep_1_strengthen(sentence, matches, converter):
        prep_strength_1(sentence, matches, converter)

    advcl_acl_prep_1_strengthen_constraint = Full(
        tokens=[
            Token(id="prep"),
            Token(id="gov"),
            Token(id="case"),
        ],
        edges=[
            Edge(child="case", parent="prep", label=[HasLabelFromList(["case"])]),
            Edge(child="prep", parent="gov", label=[HasLabelFromList(["advcl:loc"])]),
        ],
    )

    def advcl_acl_prep_1_strengthen(sentence, matches, converter):
        prep_strength_1(sentence, matches, converter)

    #框式介词加强
    def prep_strengthen_2(sentence, matches, converter):
        for cur_match in matches:
            gov = cur_match.token("gov")
            prep = cur_match.token("prep")
            case_p = cur_match.token("case_p")
            case_lc = cur_match.token("case_lc")
            case_num = len([child for child in sentence[prep].get_children() if child.get_conllu_field("deprel") == "case"])
            if case_num == 2:
                for label in cur_match.edge(prep, gov):
                    sentence[prep].replace_edge(Label(label), Label(label+ "_" + sentence[case_p].get_conllu_field("form") + "..." + sentence[case_lc].get_conllu_field("form")), sentence[gov], sentence[gov])

    nmod_prep_2_strengthen_constraint = Full(
        tokens=[
            Token(id="prep"),
            Token(id="gov"),
            Token(id="case_p", spec=[Field(field=FieldNames.TAG, value=["P"])]),
            Token(id="case_lc", spec=[Field(field=FieldNames.TAG, value=["LC"])]),
        ],
        edges=[
            Edge(child="case_p", parent="prep", label=[HasLabelFromList(["case"])]),
            Edge(child="case_lc", parent="prep", label=[HasLabelFromList(["case"])]),
            Edge(child="prep", parent="gov", label=[HasLabelFromList(["nmod:prep"])]),
        ],
    )

    def nmod_prep_2_strengthen(sentence, matches, converter):
        prep_strengthen_2(sentence, matches, converter)

    advcl_acl_prep_2_strengthen_constraint = Full(
        tokens=[
            Token(id="prep"),
            Token(id="gov"),
            Token(id="case_p", spec=[Field(field=FieldNames.TAG, value=["P"])]),
            Token(id="case_lc", spec=[Field(field=FieldNames.TAG, value=["LC"])]),
        ],
        edges=[
            Edge(child="case_p", parent="prep", label=[HasLabelFromList(["case"])]),
            Edge(child="case_lc", parent="prep", label=[HasLabelFromList(["case"])]),
            Edge(child="prep", parent="gov", label=[HasLabelFromList(["advcl:loc", "acl"])]),
        ],
    )

    def advcl_acl_prep_2_strengthen(sentence, matches, converter):
        prep_strengthen_2(sentence, matches, converter)

    #词间连词
    #有连词
    word_conj_have_alteration_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="cc", spec=[Field(field=FieldNames.TAG, value=["CC"])]),
            Token(id="conj_x"),
        ],
        edges=[
            Edge(child="cc", parent="gov", label=[HasLabelFromList(["cc"])]),
            Edge(child="conj_x", parent="gov", label=[HasLabelFromList(["conj"])]),
        ],
    )

    def word_conj_have_alteration(sentence, matches, converter):
        for cur_match in matches:
            gov = cur_match.token("gov")
            cc = cur_match.token("cc")
            conj_xs = [child for child in sentence[gov].get_children() if child.get_conllu_field("deprel") == "conj"]
            for conj_x in conj_xs:
                conj_x.replace_edge(Label("conj"), Label("conj_" + sentence[cc].get_conllu_field("form")), sentence[gov], sentence[gov])

    # Adds the type of conjunction to all conjunct relations
    eud_conj_info_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="conj")],
        edges=[
            Edge(child="conj", parent="gov", label=[HasLabelFromList(["conj"])]),
        ],
    )

    def eud_conj_info(sentence, matches, converter):
        for cur_match in matches:
            gov_id = cur_match.token("gov")
            conj_id = cur_match.token("conj")
            gov = sentence[cur_match.token("gov")]
            conj = sentence[cur_match.token("conj")]

            if conj not in converter.cc_assignments:
                continue

            for rel in cur_match.edge(cur_match.token("conj"), cur_match.token("gov")):
                if conj_id > gov_id:
                    is_cc = 0
                    i = conj_id
                    while i > gov_id and sentence[i].get_conllu_field("deprel") != "，":
                        if sentence[i].get_conllu_field("deprel") == "cc" and sentence[i].get_conllu_field("head") == conj.get_conllu_field("head"):
                            is_cc = 1
                            child_list = [child.get_conllu_field("head") for child in sentence[i].get_children()]
                            if len(child_list) == 0:
                                break
                            for j in child_list:
                                if j > conj_id or j > gov_id:
                                    is_cc = 0
                        i -= 1
                    # print(is_cc)
                    if is_cc == 1:
                        conj.replace_edge(Label(rel), Label(rel, converter.cc_assignments[conj][1]), gov, gov)
                else:
                    conj.replace_edge(Label(rel), Label(rel, converter.cc_assignments[conj][1]), gov, gov)

    #无连词、
    word_conj_havenot_alteration_constraint = Full(
        tokens=[
            Token(id="gov"),
            Token(id="punct", spec=[Field(field=FieldNames.WORD, value=["、"])]),
            Token(id="conj_x"),
        ],
        edges=[
            Edge(child="punct", parent="gov", label=[HasLabelFromList(["punct"])]),
            Edge(child="conj_x", parent="gov", label=[HasLabelFromList(["conj"])]),
        ],
    )

    def word_conj_havenot_alteration(sentence, matches, converter):
        for cur_match in matches:
            gov = cur_match.token("gov")
            child_form = [child.get_conllu_field("form") for child in sentence[gov].get_children()]
            if "cc" not in child_form:
                conj_xs = [child for child in sentence[gov].get_children() if child.get_conllu_field("deprel") == "conj"]
                for conj_x in conj_xs:
                    conj_x.replace_edge(Label("conj"), Label("conj_、"), sentence[gov], sentence[gov])





    conversion_list = [
        # Conversion(ConvTypes.BART, adverbial_clause_propagation_1_constraint, adverbial_clause_propagation_1),
        # Conversion(ConvTypes.BART, adverbial_clause_propagation_2_constraint, adverbial_clause_propagation_2),
        # Conversion(ConvTypes.BART, complex_sentences_propagation_1_constraint, complex_sentences_propagation_1),
        # Conversion(ConvTypes.BART, complex_sentences_propagation_2_constraint, complex_sentences_propagation_2),
        Conversion(ConvTypes.BART, word_nsubj_propagation_constraint, word_nsubj_propagation),
        Conversion(ConvTypes.BART, word_dobj_propagation_constraint, word_dobj_propagation),
        Conversion(ConvTypes.BART, word_nmod_compoundnn_propagation_constraint, word_nmod_compoundnn_propagation),
        Conversion(ConvTypes.BART, word_nmod_tmod_propagation_constraint, word_nmod_tmod_propagation),
        Conversion(ConvTypes.BART, word_amod_propagation_constraint, word_amod_propagation),
        Conversion(ConvTypes.BART, word_acl_propagation_constraint, word_acl_propagation),
        Conversion(ConvTypes.BART, predicate_loc_propagation_constraint, predicate_loc_propagation),
        Conversion(ConvTypes.BART, modified_propagation_constraint, modified_propagation),
        Conversion(ConvTypes.BART, advmod_propagation_constraint, advmod_propagation),
        Conversion(ConvTypes.BART, nmod_prep_propagation_constraint, nmod_prep_propagation),
        # Conversion(ConvTypes.BART, case_propagation_constraint, case_propagation),
        Conversion(ConvTypes.BART, predicate_dobj_propagation_constraint, predicate_dobj_propagation),
        Conversion(ConvTypes.BART, predicate_nsubj_propagation_constraint, predicate_nsubj_propagation),
        Conversion(ConvTypes.BART, verb_advmod_propagation_constraint, verb_advmod_propagation),
        # Conversion(ConvTypes.BART, aux_propagation_constraint, aux_propagation),
        Conversion(ConvTypes.BART, extra_appos_propagation_constraint, extra_appos_propagation),
        Conversion(ConvTypes.BART, compoundvc_propagation_constraint, compoundvc_propagation),
        Conversion(ConvTypes.BART, passivization_alternation_constraint, passivization_alternation),
        Conversion(ConvTypes.BART, aux_ba_alternative_constraint, aux_ba_alternative),
        Conversion(ConvTypes.BART, amod_alternative_constraint, amod_alternative),
        Conversion(ConvTypes.BART, acl_dobj_alternative_constraint, acl_dobj_alternative),
        Conversion(ConvTypes.BART, acl_nsubj_alternative_constraint, acl_nsubj_alternative),
        Conversion(ConvTypes.BART, omit_nsubj_propagation_constraint, omit_nsubj_propagation),
        Conversion(ConvTypes.BART, omit_dobj_propagation_constraint, omit_dobj_propagation),

        Conversion(ConvTypes.BART, ccomp_propagation_constraint, ccomp_propagation),
        Conversion(ConvTypes.BART, nmod_prep_1_strengthen_constraint, nmod_prep_1_strengthen),
        Conversion(ConvTypes.BART, advcl_acl_prep_1_strengthen_constraint, advcl_acl_prep_1_strengthen),
        Conversion(ConvTypes.BART, nmod_prep_2_strengthen_constraint, nmod_prep_2_strengthen),
        Conversion(ConvTypes.BART, advcl_acl_prep_2_strengthen_constraint, advcl_acl_prep_2_strengthen),
        # Conversion(ConvTypes.BART, word_conj_have_alteration_constraint, word_conj_have_alteration),
        # Conversion(ConvTypes.BART, word_conj_havenot_alteration_constraint, word_conj_havenot_alteration)

        Conversion(ConvTypes.BART, eud_conj_info_constraint, eud_conj_info),
    ]
    return {conversion.name: conversion for conversion in conversion_list}


# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++ #


def remove_funcs(conversions, enhanced, enhanced_plus_plus, enhanced_extra, remove_enhanced_extra_info, remove_node_adding_conversions, remove_unc, query_mode, funcs_to_cancel):
    if not enhanced:
        conversions = {conversion.name: conversion for conversion in conversions.values() if conversion.conv_type != ConvTypes.EUD}
    if not enhanced_plus_plus:
        conversions = {conversion.name: conversion for conversion in conversions.values() if conversion.conv_type != ConvTypes.EUDPP}
    if not enhanced_extra:
        conversions = {conversion.name: conversion for conversion in conversions.values() if conversion.conv_type != ConvTypes.BART}
    if remove_enhanced_extra_info:
        conversions.pop('eud_conj_info', None)
        conversions.pop('eud_prep_patterns', None)
    if remove_node_adding_conversions:
        # no need to cancel extra_inner_weak_modifier_verb_reconstruction as we have a special treatment there
        conversions.pop('eudpp_expand_prep_conjunctions', None)
        conversions.pop('eudpp_expand_pp_conjunctions', None)
    if remove_unc:
        for func_name in ['extra_dep_propagation', 'extra_compound_propagation', 'extra_conj_propagation_of_poss', 'extra_conj_propagation_of_nmods_forward', 'extra_conj_propagation_of_nmods_backwards', 'extra_advmod_propagation', 'extra_advcl_ambiguous_propagation']:
            conversions.pop(func_name, None)
    if query_mode:
        for func_name in conversions.keys():
            if func_name in ['extra_nmod_advmod_reconstruction', 'extra_copula_reconstruction', 'extra_evidential_basic_reconstruction', 'extra_evidential_xcomp_reconstruction', 'extra_inner_weak_modifier_verb_reconstruction', 'extra_aspectual_reconstruction', 'eud_correct_subj_pass', 'eud_conj_info', 'eud_prep_patterns', 'eudpp_process_simple_2wp', 'eudpp_process_complex_2wp', 'eudpp_process_3wp', 'eudpp_demote_quantificational_modifiers']:
                conversions.pop(func_name, None)
    if funcs_to_cancel:
        for func_to_cancel in funcs_to_cancel:
            conversions.pop(func_to_cancel, None)

    return conversions


class Convert:
    def __init__(self, *args):
        self.args = args
        self.iids = dict()
        self.cc_assignments = dict()
        # TODO - use kwargs
        self.remove_enhanced_extra_info = args[5]  # should be in the index of remove_enhanced_extra_info param
        self.remove_bart_extra_info = args[6]  # should be in the index of remove_bart_extra_info param

    def __call__(self):
        return self.convert(*self.args)

    def get_rel_set(self, converted_sentence):
        return set([(str(head.get_conllu_field("id")),
                     rel.to_str(self.remove_enhanced_extra_info, self.remove_bart_extra_info),
                     str(tok.get_conllu_field("id"))) for tok in converted_sentence
                    for (head, rels) in tok.get_new_relations() for rel in rels])

    def convert(self, parsed, enhanced, enhanced_plus_plus, enhanced_extra, conv_iterations, remove_enhanced_extra_info,
                remove_bart_extra_info, remove_node_adding_conversions, remove_unc, query_mode, funcs_to_cancel,
                ud_version=1, one_time_initialized_conversions=None):

        if one_time_initialized_conversions:
            conversions = one_time_initialized_conversions
        else:
            conversions = init_conversions(remove_node_adding_conversions, ud_version)
        conversions = remove_funcs(conversions, enhanced, enhanced_plus_plus, enhanced_extra,
                                   remove_enhanced_extra_info,
                                   remove_node_adding_conversions, remove_unc, query_mode, funcs_to_cancel)

        i = 0
        updated = []
        for sentence in parsed:
            sentence_as_list = [t for t in sentence if t.get_conllu_field("id").major != 0]
            assign_ccs_to_conjs(sentence_as_list, self.cc_assignments)
            i = max(i, self.convert_sentence(sentence_as_list, conversions, conv_iterations))
            updated.append(sentence_as_list)

        return updated, i

    def convert_sentence(self, sentence: Sequence[Token], conversions, conv_iterations: int):
        last_converted_sentence = None
        i = 0
        on_last_iter = ["extra_amod_propagation"]
        do_last_iter = []
        # we iterate till convergence or till user defined maximum is reached - the first to come.
        matcher = Matcher([NamedConstraint(conversion_name, conversion.constraint)
                           for conversion_name, conversion in conversions.items()])
        while i < conv_iterations:
            last_converted_sentence = self.get_rel_set(sentence)
            m = matcher(sentence)
            for conv_name in m.names():
                if conv_name in on_last_iter:
                    do_last_iter.append(conv_name)
                    continue
                matches = m.matches_for(conv_name)
                conversions[conv_name].transformation(sentence, matches, self)
            if self.get_rel_set(sentence) == last_converted_sentence:
                break
            i += 1

        for conv_name in do_last_iter:
            m = matcher(sentence)
            matches = m.matches_for(conv_name)
            conversions[conv_name].transformation(sentence, matches, self)
            if self.get_rel_set(sentence) != last_converted_sentence:
                i += 1

        return i
