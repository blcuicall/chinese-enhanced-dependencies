from constraints import *

two_word_preps_regular = {"across_from", "along_with", "alongside_of", "apart_from", "as_for", "as_from", "as_of", "as_per", "as_to", "aside_from", "based_on", "close_by", "close_to", "contrary_to", "compared_to", "compared_with", " depending_on", "except_for", "exclusive_of", "far_from", "followed_by", "inside_of", "irrespective_of", "next_to", "near_to", "off_of", "out_of", "outside_of", "owing_to", "preliminary_to", "preparatory_to", "previous_to", "prior_to", "pursuant_to", "regardless_of", "subsequent_to", "thanks_to", "together_with"}

eudpp_process_simple_2wp_constraint = Full(
    tokens=[
        Token(id="w1", no_children=True),
        Token(id="w2", no_children=True),
        Token(id="common_parent")],
    edges=[
        Edge(child="w1", parent="common_parent", label=[HasLabelFromList(["case", "advmod"])]),
        Edge(child="w2", parent="common_parent", label=[HasLabelFromList(["case"])])
    ],
    distances=[ExactDistance("w1", "w2", distance=0)],
    concats=[TokenPair(two_word_preps_regular, "w1", "w2")]
)