'''
Authors: Aaron Mueller, Andrew Blair-Stanek
Date: 24 October 2018
Course: Natural Language Processing
Instructor: Jason Eisner
Assignment: HW4 -- Parsing
'''
# Basic implementation of (non-probabilistic) Earley parser

import sys
import numpy
import math
# import datetime


# This class represents a single grammar rule read in from .GR file
class GrRule:
    def __init__(self, prob, lhs, rhs):
        self.prob = prob
        self.weight = -math.log(self.prob, 2)
        self.lhs = lhs
        self.rhs = rhs
        self.first_rhs_is_nonterminal = False

    def to_string(self, index_period = -1):
        s = self.lhs + " -->"
        for i in range(0, len(self.rhs)):
            if i == index_period:
                s += " ."
            s += " " + self.rhs[i]
        if index_period == len(self.rhs):
            s += " . "
        return s


    def print(self, index_period = -1):
        s = self.to_string(index_period)
        print(s, end="")


# This class represents a single entry (i.e., the rule, the start index, and the period index)
class Entry:
    def __init__(self, rule_index, start_index, period_index, weight):
        self.rule_index = rule_index
        self.start_index = start_index
        self.period_index = period_index
        self.weight = weight
        '''
        # Below is the backpointer to the entry holding the prior state of the same rule (hence, horizontal)
        # Example 1: if the entry is  S -> NP VP .  then this will point to the S -> NP . VP entry
        # Example 2: if the entry is  S -> NP . VP  then this will be None
        # Example 3: if the entry is  S -> . NP VP  then this will be None
        # Example 4: if the entry is  A -> B and C . then this will point to the A -> B and . C entry
        '''
        self.horiz_backpointer = None
        '''
        # Below is the backpointer to the entry for the rule just to the LEFT of the period (hence, vertical)
        # Example 1: if the entry is  S -> NP VP .  then this will point to the entry for the VP
        # Example 2: if the entry is  S -> NP . VP  then this will point to the entry for the NP
        # Example 3: if the entry is  S -> . NP VP  then this will be None
        # Example 4: if the entry is  A -> B and . C . then this will be None (since "and" is a terminal)
        '''
        self.vert_backpointer = None

        # Setting this to true means to ignore the entry in the future.
        # This approach is suggested as OK on the bottom of page R-4 and top of R-5
        self.is_null = False

        # This is used solely for debugging purposes when debugging is turned on
        self.debug_info = None


# This class represents the entire parser
class EarleyParser:
    def __init__(self):
        self.grammar_rules = None
        self.chart = None
        self.states_added = None
        self.dict_lhs = {}  # This is a dictionary (i.e. hashtable) of all items on the l.h.s. of a rule

    # This helper function determines whether a string is a non-terminal in the set of grammar rules we have
    def is_nonterminal(self, string):
        if string in self.dict_lhs:
            return True
        return False

    # Read grammar rules from an external file.
    # The rules are read into a list of GrRule.
    def read_grammar_rules(self, grammar_filename):
        self.grammar_rules = []
        with open(grammar_filename) as infile:
            for line in infile:
                if len(line) > 2:
                    arr = line.split()
                    prob = float(arr.pop(0))
                    lhs = arr.pop(0)
                    self.dict_lhs[lhs] = True # add left-hand-side string to the dictionary (i.e. hash table)
                    self.grammar_rules.append(GrRule(prob, lhs, arr))

        # For each rule, figure out whether its first item on the RHS is a non-terminal.
        # This is mainly an optimization for the predictor() function, which starts with the
        # period before the first item, which is why we care about the first item on the RHS
        for rule in self.grammar_rules:
            if rule.rhs[0] in self.dict_lhs:
                rule.first_rhs_is_nonterminal = True

    # This is the first operator in Earley (out of three), see J&M p.444
    # It expands a possible operator into multiple
    def predictor(self, state, i_col, next_cat, left_corners, word):
        # If the category we are trying to predict is not a possible left-hand-corner, do no more
        if next_cat not in left_corners:
            return

        # The following lines implement the "Batch Duplicate check" suggested in section E.1 of HW4
        tuple_for_batch = (next_cat, i_col, "Batch Duplicate")
        if tuple_for_batch in self.states_added:
            return # do not add this batch to this column (i.e. i_col) if already added
        self.states_added[tuple_for_batch] = True # add to prevent future re-adding

        # The following code performs the actual meat of predictor
        for i_rule in range(0, len(self.grammar_rules)):
            rule = self.grammar_rules[i_rule]
            if rule.lhs == next_cat and \
                    ((rule.first_rhs_is_nonterminal and rule.rhs[0] in left_corners) or \
                     (not rule.first_rhs_is_nonterminal and rule.rhs[0] == word)):
                new_entry = Entry(i_rule, i_col, 0, self.grammar_rules[i_rule].weight)
                self.enqueue(new_entry, i_col, "PREDICTOR") # attempt to add new state, if not already added


    # This is the second operator in Earley (out of three), see J&M p.444
    # It puts a new completed entry in the NEXT column of the chart
    def scanner(self, state, i_col):
        new_entry = Entry(state.rule_index,
                          state.start_index,
                          state.period_index+1,
                          state.weight) # scanning a terminal doesn't change probabilities; use state's weight

        # We keep a horizontal backpointer only if it is necessary for interpreting the rule
        # For example, if new_entry will be  A -> B and . C  then backpoint to  A -> B . and C
        # For example, if new_entry will be  NP -> a majority . of N  then backpoint to  NP -> a . majority of N
        # But, for example, do not backpoint if this is  NP --> Papa .
        if state.period_index > 0:
            new_entry.horiz_backpointer = state

        self.enqueue(new_entry, i_col +1, "SCANNER")


    # This is the third operator in Earley, called "Completer" by J&M p.444
    # It goes back to PRIOR chart entries to find "customers" for a completed state
    def attach(self, state, i_col, left_corners):
        match_seeking = self.grammar_rules[state.rule_index].lhs
        icol2 = state.start_index
        for irow2 in range(0, len(self.chart[icol2])):
            entry2 = self.chart[icol2][irow2]
            if not entry2.is_null and entry2.period_index < len(self.grammar_rules[entry2.rule_index].rhs):
                # then this may be seeking a completion
                possible_match = self.grammar_rules[entry2.rule_index].rhs[entry2.period_index]
                if possible_match == match_seeking:  # if this is true, we potentially have a "customer" to "attach"
                    rhs_consistent = False # check whether the next part of the relevant rule is consistent
                    rhs_length = len(self.grammar_rules[entry2.rule_index].rhs)

                    if entry2.period_index == (rhs_length - 1):
                        rhs_consistent = True # r.h.s. will always be consistent if state precisely completes it
                    elif left_corners != None: # left_corners will be None only if we are in the very last column
                        # we need to retrieve the first item on the r.h.s. that would remain uncompleted
                        if self.grammar_rules[entry2.rule_index].rhs[entry2.period_index+1] in left_corners:
                            rhs_consistent = True # consistent only if the next r.h.s. rule is in left-corners

                    if rhs_consistent: # if the right hand side is consistent, add the attached entry to the chart
                        weight = entry2.weight + state.weight
                        new_entry = Entry(entry2.rule_index,
                                          entry2.start_index,
                                          entry2.period_index + 1,
                                          weight)
                        new_entry.vert_backpointer = state
                        if entry2.period_index > 0:
                            new_entry.horiz_backpointer = entry2

                        self.enqueue(new_entry, i_col, "ATTACH")


    # This is a crucial helper function in Earley, see J&M p.444
    # It tries to add a state to the chart a column i_col.
    # It only adds that state if it has not already been added in i_col.
    def enqueue(self, state, column, calling_function):
        tuple_version_of_state = (state.rule_index,
                                  state.start_index,
                                  state.period_index,
                                  column) # Column is in the tuple so there is only one hash table "states_added"

        if tuple_version_of_state in self.states_added and calling_function == "ATTACH":
            existing_state = self.states_added[tuple_version_of_state]

            # If there is an existing state that has a lower weight than state, then do not enqueue
            # state; just return instead
            if existing_state.weight <= state.weight:
                return
            else: # but if the existing state has a higher weight, remove it so we can enqueue state
                existing_state.is_null = True # disregard the existing, higher-weight state
                del self.states_added[tuple_version_of_state] # remove the existing, higher-weight state from dict

        if tuple_version_of_state not in self.states_added:
            self.chart[column].append(state)
            self.states_added[tuple_version_of_state] = state

            if False: # Turn this to True to turn on debugging information
                s = str(state.start_index) + " "
                s += self.grammar_rules[state.rule_index].to_string(state.period_index)
                s += " (weight = " + str(state.weight) + ")"
                s += " (Added by " + calling_function + " at Col = " + \
                        str(column) + " Row = " + str(len(self.chart[column]) - 1) + ")"
                print(s)
                state.debug_info = s


    # This function starts the first column with all possible expansions of ROOT
    def add_ROOT_expansions(self):
        for i in range(0, len(self.grammar_rules)):
            if self.grammar_rules[i].lhs == "ROOT":
                self.enqueue(Entry(i, 0, 0, self.grammar_rules[i].weight), 0, "DUMMY START STATE")

    # This function builds a dictionary (i.e. hash table) of all possible left corners
    def get_left_corners(self, word):
        d = {}
        d[word] = True # the word is in its own left corner
        old_count = 0 # tracks old size of d
        new_count = 1 # tracks new size of d (which is 1, since we just added the word itself)
        while old_count < new_count: # keep going as long as the prior run increased d's size
            for rule in self.grammar_rules: # iterating without index is faster here, and we don't need the index
                if rule.lhs not in d and rule.rhs[0] in d:
                    d[rule.lhs] = True # then add the left-hand side to the hash
            old_count = new_count
            new_count = len(d)

        return d


    # This function actually parses a particular sentence
    def parse(self, sentence):
        words = sentence.split()

        self.chart = [[] for x in range(0, len(words)+1)] # create the chart
        self.states_added = {} # dictionary (i.e. hash table) of states used
        self.add_ROOT_expansions() # add all ROOT rules to the start of the chart

        for i_col in range(0, len(words)+1):  # iterates over columns in Earley chart
            if i_col < len(words):
                cur_word = words[i_col]
                left_corners = self.get_left_corners(cur_word) # used for left-corner filter
            else: # then we are on the very last column
                cur_word = None
                left_corners = None # there is no left-corner filter on the very last column

            i_row = 0  # this index into chart[i] keeps track of which item remains to predict or scan
            while i_row < len(self.chart[i_col]):  # chart[i] can have additional items added during this loop
                state = self.chart[i_col][i_row]

                if not state.is_null: # i.e. if we have not eliminated it because there is another lower-weight entry
                    len_rhs = len(self.grammar_rules[state.rule_index].rhs)
                    period_index = state.period_index

                    if period_index > len_rhs:  # this means there is an error
                        sys.exit("ERROR: period_index > len_rhs")

                    incomplete = period_index < len_rhs # an entry is "complete" if all rules are left of the period

                    if incomplete:
                        if i_col < len(words): # predictor and scanner never run on the very last column
                            next_cat = self.grammar_rules[state.rule_index].rhs[period_index]
                            if next_cat == cur_word:
                                self.scanner(state, i_col)
                            else:
                                self.predictor(state, i_col, next_cat, left_corners, cur_word)
                    else:  # if we are here, we have a completed item and we need to run ATTACH (a/k/a COMPLETE)
                        self.attach(state, i_col, left_corners)

                i_row += 1


    # This recursive helper function prints the subtree
    def print_entry(self, entry):
        gr_rule = self.grammar_rules[entry.rule_index]

        print("(" + gr_rule.lhs + " ", end="")

        # construct a list of all entries making up this rule, by following pointers
        list_entries = []
        ref_entry = entry
        while ref_entry is not None:
            list_entries.append(ref_entry)
            ref_entry = ref_entry.horiz_backpointer

        # now walk through this list printing all the of subtrees
        index_rhs = 0
        while len(list_entries) > 0:
            sub_entry = list_entries.pop()
            if sub_entry.vert_backpointer is None:
                print(gr_rule.rhs[index_rhs], end="")
            else:
                self.print_entry(sub_entry.vert_backpointer)
            index_rhs += 1

        print(")", end="")


    # This function does the actual printing
    def print(self):
        # first, find all instances of ROOT in the final column
        count_completions = 0
        min_entry = None
        min_weight = float('inf')
        for entry in self.chart[len(self.chart)-1]:
            if self.grammar_rules[entry.rule_index].lhs == "ROOT" and \
                    entry.start_index == 0 and \
                    entry.period_index == len(self.grammar_rules[entry.rule_index].rhs) and \
                    not entry.is_null:
                if entry.weight < min_weight:
                    min_weight = entry.weight
                    min_entry = entry
        if min_entry is not None:
            self.print_entry(min_entry)
            count_completions += 1
            print("\n" + str(min_entry.weight))  # print the log-2 weight, as required for HW4
        if count_completions == 0:
            print("NONE")
        elif count_completions > 1:
            print("ERROR: Multiple trees printed out; should have printed only one")


# This main function coordinates all the code to run
def main():
    if len(sys.argv) != 3:
        sys.exit("Usage: basic_earley grammar.gr sentences.sen")
    parser = EarleyParser()
    parser.read_grammar_rules(sys.argv[1])

    sen_file = open(sys.argv[2])  # open .SEN file
    for sentence in sen_file:
        if len(sentence.strip()) > 0:
            parser.parse(sentence)
            parser.print()

main() # starts execution
