import copy

from app.objects.secondclass.c_fact import Fact
from app.objects.c_operation import Operation
from app.objects.secondclass.c_requirement import Requirement


class LogicalPlanner:
    """
    The response planner is made to support indefinite defensive operations. Setup abilities are run once when an
    operation first starts, or when an agent first connects to an ongoing operation. Detection abilities are run
    repeatedly. Hunt abilities are run when certain detection abilities have produced detections. Response abilities
    are run when there are unaddressed detections.
    Both hunt and response abilities can be repeatable. However, they will only be repeated if there is a detection that
    has not been hunted for or responded to, respectively.
    Detection and hunt abilities should not be repeated if they have produced results that have not been addressed yet.
    This last part needs to be implemented.
    """

    def __init__(self, operation, planning_svc, stopping_conditions=()):
        self.operation = operation
        self.planning_svc = planning_svc
        self.stopping_conditions = stopping_conditions
        self.stopping_condition_met = False
        self.state_machine = ['setup', 'detection', 'hunt', 'response']
        self.next_bucket = 'setup'
        self.has_been_setup = []
        self.links_hunted = set()
        self.links_responded = set()
        self.processed = []
        self.severity = dict()

    async def execute(self):
        await self._process_link_severities()
        await self.planning_svc.execute_planner(self)

    async def setup(self):
        for agent in [ag for ag in self.operation.agents if ag.paw not in self.has_been_setup]:
            self.has_been_setup.append(agent.paw)
            self.severity[agent.paw] = 0
            await self.planning_svc.exhaust_bucket(self, 'setup', self.operation, agent, batch=True)
        self.next_bucket = await self.planning_svc.default_next_bucket('setup', self.state_machine)

    async def detection(self):
        await self.planning_svc.exhaust_bucket(self, 'detection', self.operation, batch=True)
        self.next_bucket = await self.planning_svc.default_next_bucket('detection', self.state_machine)

    async def hunt(self):
        await self._do_reactive_bucket(bucket='hunt')
        self.next_bucket = await self.planning_svc.default_next_bucket('hunt', self.state_machine)

    async def response(self):
        await self._do_reactive_bucket(bucket='response')
        self.next_bucket = 'detection'

    """ PRIVATE """

    async def _process_link_severities(self):
        """
        If a completed link produced a detection and had a severity modifier, modify its paw's severity score.
        """
        for link in [lnk for lnk in self.operation.chain if lnk not in self.processed]:
            if link.ability.tactic in ['detection', 'response'] and self._get_produced_facts(link) \
                    and 'severity_modifier' in link.ability.additional_info:
                self.severity[link.paw] += link.ability.additional_info['severity_modifier']
            self.processed.append(link)

    async def _do_reactive_bucket(self, bucket):
        """
        Reactive buckets are buckets that only run abilities when there is an existing detection to be responded to.
        Detections that are responded to are kept track of in link storage sets.
        Response abilities that have a severity requirement that isn't met are skipped.
        """
        link_storage = self._get_link_storage(bucket)
        links = await self.planning_svc.get_links(planner=self, operation=self.operation, buckets=[bucket])
        links_to_apply = []
        links_being_addressed = set()
        for link in links:
            if bucket == 'response' and 'severity_requirement' in link.ability.additional_info and \
                    int(link.ability.additional_info['severity_requirement']) > self.severity[link.paw]:
                continue
            if link.used:
                check_paw_prov = True if bucket in ['response'] else False
                unaddressed_parents = await self._get_unaddressed_parent_links(link, link_storage, check_paw_prov)
                if len(unaddressed_parents):
                    links_to_apply.append(link)
                    links_being_addressed.update(unaddressed_parents)
            else:
                links_to_apply.append(link)
        link_storage.update(list(links_being_addressed))
        links_to_apply = self._remove_duplicate_links(links_to_apply)
        await self._run_links(links_to_apply)

    def _get_link_storage(self, bucket):
        storage = dict(
            hunt=self.links_hunted,
            response=self.links_responded
        )
        return storage[bucket]

    async def _get_unaddressed_parent_links(self, link, link_storage, check_paw_prov=False):
        """
        Unaddressed parent links are those links that produced [a] detection(s) that is/are used by the link-to-be-
        applied. A potential parent link is one that contains a fact that is used by the link-to-be-applied in one of
        its created relationships. These potential parent links are then checked to ensure that they actually produced
        detection(s) that the link-to-be-applied uses.
        """
        unaddressed_links = [unaddressed for unaddressed in self._get_parent_links(link, check_paw_prov) if
                             unaddressed not in link_storage]
        unaddressed_parents = []
        for ul in unaddressed_links:
            if await self._do_parent_relationships_satisfy_link_requirements(link, ul):
                unaddressed_parents.append(ul)
        return unaddressed_parents

    def _get_parent_links(self, link, check_paw_prov=False):
        """
        Any completed link with relationships that contain at least one fact used by the link-to-be-applied is
        considered a potential parent.
        """
        parent_links = set()
        link_paw = link.paw if check_paw_prov else None
        for fact in link.used:
            parent_links.update(self._links_with_fact_in_relationship(fact, link_paw))
        return parent_links

    def _links_with_fact_in_relationship(self, fact, paw=None):
        """
        Get all the links in the operation's chain that contain the fact in at least one relationship.
        """
        links_with_fact = []
        for link in self.operation.chain if paw is None else [lnk for lnk in self.operation.chain if lnk.paw == paw]:
            if any(self._fact_in_relationship(fact, rel) for rel in link.relationships):
                links_with_fact.append(link)
        return links_with_fact

    def _fact_in_relationship(self, fact, relationship):
        for f in [relationship.source, relationship.target]:
            if f and self._do_facts_match(f, fact):
                return True
        return False

    async def _do_parent_relationships_satisfy_link_requirements(self, link, potential_parent):
        """
        A potential parent link that produces a relationship that doesn't satisfy any of the link-to-be-applied's
        requirements isn't really a parent. If the link-to-be-applied doesn't have any requirements associated with the
        fact produced by the potential parent, then that works too - the potential parent is an actual parent.
        """
        used_facts = [fact for fact in link.used for rel in potential_parent.relationships if
                      self._fact_in_relationship(fact, rel)]
        relevant_requirements_and_facts = dict()
        for fact in used_facts:
            rel_reqs_for_fact = self._get_relevant_requirements_for_fact_in_link(link, fact)
            if not rel_reqs_for_fact and self._is_fact_produced(fact, potential_parent):
                return 1
            else:
                for rel_req in rel_reqs_for_fact:
                    req_unique = self._unique_for_requirement(rel_req)
                    if req_unique in relevant_requirements_and_facts:
                        relevant_requirements_and_facts[req_unique]['facts'].append(fact)
                    else:
                        relevant_requirements_and_facts[req_unique] = dict(requirement=rel_req, facts=[fact])
        links_with_relevant_reqs, verifier_operation = self._create_test_op_and_links(link, potential_parent,
                                                                                      relevant_requirements_and_facts)
        return len(await self.planning_svc.remove_links_missing_requirements(links_with_relevant_reqs,
                                                                             verifier_operation)) if \
            relevant_requirements_and_facts else 0

    @staticmethod
    def _get_relevant_requirements_for_fact_in_link(link, fact):
        """
        Relevant requirements for a fact are those that involve the fact somehow.
        """
        relevant_requirements = []
        for req in link.ability.requirements:
            for req_match in req.relationship_match:
                if fact.trait == req_match['source'] or 'target' in req_match and fact.trait == req_match['target']:
                    relevant_requirements.append(Requirement(module=req.module, relationship_match=[req_match]))
        return relevant_requirements

    @staticmethod
    def _unique_for_requirement(requirement):
        """
        A unique string used to identify a requirement.
        """
        rel_match = requirement.relationship_match[0]
        unique = requirement.module + rel_match['source']
        for field in ['edge', 'target']:
            if field in rel_match:
                unique += rel_match[field]
        return unique

    def _create_test_op_and_links(self, link, potential_parent, relevant_requirements_and_facts):
        """
        This function creates a test operation and test links. The test operation contains a copy of the potential
        parent in its chain. This copy link is given all the facts that it produced, determined by
        set(facts_in_relationships) - set(used_facts).
        The test links are copies of the link-to-be-applied. Each of these is given one relevant requirement to
        be tested for.
        Relevant requirements are provided by the calling function, but then filtered to ensure that each requirement
        uses at least one fact produced by the parent.
        """
        verifier_operation = Operation(name='verifier', agents=[], adversary=None, planner=self.operation.planner)
        potential_parent_copy = copy.copy(potential_parent)
        produced_facts = self._get_produced_facts(potential_parent)
        potential_parent_copy.facts = [Fact(trait=fact.trait, value=fact.value, collected_by=potential_parent.paw) for
                                       fact in produced_facts]
        verifier_operation.chain.append(potential_parent_copy)
        filtered_rel_reqs_and_facts = self._filter_reqs_by_used_facts(relevant_requirements_and_facts, produced_facts)
        links_with_relevant_reqs_and_facts = self._create_test_links(link, filtered_rel_reqs_and_facts)
        return links_with_relevant_reqs_and_facts, verifier_operation

    def _get_produced_facts(self, link):
        """
        Facts that are the results of parsing output, and not just used facts that are part of a relationship.
        """
        return [fact for fact in self._facts_from_link_relationships(link) if not self._is_fact_used(fact, link)]

    @staticmethod
    def _facts_from_link_relationships(link):
        """
        Extracting facts from relationships.
        """
        relationship_facts = []
        for rel in link.relationships:
            relationship_facts.extend([rel.source, rel.target] if rel.target else [rel.source])
        return relationship_facts

    @staticmethod
    def _is_fact_used(fact, link):
        for used in link.used:
            if fact.trait == used.trait and fact.value == used.value:
                return True
        return False

    def _filter_reqs_by_used_facts(self, requirements_and_facts, filter_facts):
        """
        Each requirement should contain at least one fact within filter_facts. In this context, a requirement that
        doesn't use any of the facts produced by the potential parent link is considered to be unsatisfied, and so is
        removed.
        Facts used by the link-to-be-applied are also replaced by the facts produced by the potential parent. This is to
        effectively enforce paw_provenance requirements, and any other similar requirements.
        """
        filtered_reqs_and_facts = dict()
        for req in requirements_and_facts:
            filtered_facts = self._replace_matched_facts_with_filter_facts(requirements_and_facts[req], filter_facts)
            if filtered_facts:
                filtered_reqs_and_facts[req] = dict(requirement=requirements_and_facts[req]['requirement'],
                                                    facts=filtered_facts)
        return filtered_reqs_and_facts

    def _replace_matched_facts_with_filter_facts(self, requirement_and_facts, filter_facts):
        filtered_facts = []
        contains_filter_fact = False
        for req_fact in requirement_and_facts['facts']:
            for ff in filter_facts:
                if self._do_facts_match(req_fact, ff):
                    contains_filter_fact = True
                    filtered_facts.append(ff)
        return filtered_facts if contains_filter_fact else False

    @staticmethod
    def _do_facts_match(fact1, fact2):
        return fact1.trait == fact2.trait and fact1.value == fact2.value

    def _is_fact_produced(self, fact, parent_link):
        return any(self._do_facts_match(fact, parent_fact) for parent_fact in self._get_produced_facts(parent_link))

    @staticmethod
    def _create_test_links(original_link, requirements_and_facts):
        """
        Test links are copies of the original link, but with some modifications. They contain only one requirement, and
        only those used facts that are relevant to the requirement. These links are then tested to see if they satisfy
        their given requirements.
        """
        links = []
        for req in requirements_and_facts:
            link_with_req = copy.copy(original_link)
            ability_with_req = copy.copy(original_link.ability)
            ability_with_req.requirements = [requirements_and_facts[req]['requirement']]
            link_with_req.ability = ability_with_req
            link_with_req.used = requirements_and_facts[req]['facts']
            links.append(link_with_req)
        return links

    @staticmethod
    def _remove_duplicate_links(links):
        """
        As many abilities are repeatable, it's possible that the same link gets run twice during the execution of a
        bucket. This is to prevent that from happening.
        """
        unique_links = []
        for link in links:
            if not any(link.command == ul.command and link.paw == ul.paw for ul in unique_links):
                unique_links.append(link)
        return unique_links

    async def _is_detection_not_responded_to(self, new_link):
        """
        We don't want to repeat the same detection ability if we know it's just going to produce the same result over
        again. This checks to see if we're repeating a detection ability that produced relationships but hasn't been
        responded to yet.
        """
        for link in [lnk for lnk in self.processed if lnk.relationships and lnk not in self.links_responded]:
            if new_link.command == link.command and new_link.paw == link.paw:
                return True
        return False

    async def _run_links(self, links):
        """
        Apply and execute the bucket's links.
        """
        link_ids = []
        for link in links:
            link_ids.append(await self.operation.apply(link))
        await self.planning_svc.execute_links(self, self.operation, link_ids, True)
