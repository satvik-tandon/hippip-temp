#!/usr/bin/env python

from interaction import Interaction

class Interactions:
    def __init__(self):
        self.interactions = {}

    def add(self, interaction):
        if not interaction.eid1 in self.interactions:
            self.interactions[interaction.eid1] = {}
        self.interactions[interaction.eid1][interaction.eid2] = interaction

    def get(self, eid1, eid2):
        if eid1 in self.interactions:
            if eid2 in self.interactions[eid1]:
                return self.interactions[eid1][eid2]

        # not found, so create a new interaction
        interaction = Interaction(eid1, eid2)
        self.add(interaction)

        return interaction

    def iter(self):
        for eid1 in self.interactions:
            for eid2 in self.interactions[eid1]:
                yield self.interactions[eid1][eid2]

    def contains(self, eid1, eid2):
        if eid1 in self.interactions:
            return eid2 in self.interactions[eid1]
        return False


