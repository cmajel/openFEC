import sqlalchemy as sa
from flask_apispec import doc

from webservices import args
from webservices import docs
from webservices import utils
from webservices import schemas
from webservices import exceptions
from webservices.common import models
from webservices.common.views import ApiResource


def filter_year(model, query, years):
    return query.filter(
        sa.or_(*[
            sa.and_(
                sa.or_(
                    sa.extract('year', model.last_file_date) >= year,
                    model.last_file_date == None,
                ),
                sa.extract('year', model.first_file_date) <= year,
            )
            for year in years
        ])
    )  # noqa


@doc(
    tags=['committee'],
    description=docs.COMMITTEE_LIST,
)
class CommitteeList(ApiResource):

    model = models.Committee
    schema = schemas.CommitteeSchema
    page_schema = schemas.CommitteePageSchema
    aliases = {'receipts': models.CommitteeSearch.receipts}

    filter_multi_fields = [
        ('committee_id', models.Committee.committee_id),
        ('designation', models.Committee.designation),
        ('organization_type', models.Committee.organization_type),
        ('state', models.Committee.state),
        ('party', models.Committee.party),
        ('committee_type', models.Committee.committee_type),
    ]
    filter_range_fields = [
        (('min_first_file_date', 'max_first_file_date'), models.Committee.first_file_date),
    ]

    @property
    def args(self):
        return utils.extend(
            args.paging,
            args.committee,
            args.committee_list,
            args.make_sort_args(
                default='name',
                validator=args.IndexValidator(
                    models.Committee,
                    extra=list(self.aliases.keys()),
                ),
            ),
        )

    def build_query(self, **kwargs):
        query = super().build_query(**kwargs)

        if {'receipts', '-receipts'}.intersection(kwargs.get('sort', [])) and 'q' not in kwargs:
            raise exceptions.ApiError(
                'Cannot sort on receipts when parameter "q" is not set',
                status_code=422,
            )

        if kwargs.get('candidate_id'):
            query = query.filter(
                models.Committee.candidate_ids.overlap(kwargs['candidate_id'])
            )

        if kwargs.get('q'):
            query = utils.search_text(
                query.join(
                    models.CommitteeSearch,
                    models.Committee.committee_id == models.CommitteeSearch.id,
                ),
                models.CommitteeSearch.fulltxt,
                kwargs['q'],
            ).distinct()

        if kwargs.get('treasurer_name'):
            query = utils.search_text(
                query,
                models.Committee.treasurer_text,
                kwargs['treasurer_name'],
            )

        if kwargs.get('name'):
            query = query.filter(models.Committee.name.ilike('%{}%'.format(kwargs['name'])))

        if kwargs.get('year'):
            query = filter_year(models.Committee, query, kwargs['year'])

        if kwargs.get('cycle'):
            query = query.filter(models.Committee.cycles.overlap(kwargs['cycle']))

        return query


@doc(
    tags=['committee'],
    description=docs.COMMITTEE_DETAIL,
    params={
        'candidate_id': {'description': docs.CANDIDATE_ID},
        'committee_id': {'description': docs.COMMITTEE_ID},
    },
)
class CommitteeView(ApiResource):

    model = models.CommitteeDetail
    schema = schemas.CommitteeDetailSchema
    page_schema = schemas.CommitteeDetailPageSchema

    filter_multi_fields = [
        ('designation', models.CommitteeDetail.designation),
        ('organization_type', models.CommitteeDetail.organization_type),
        ('committee_type', models.CommitteeDetail.committee_type),
    ]

    @property
    def args(self):
        return utils.extend(
            args.paging,
            args.committee,
            args.make_sort_args(
                default='name',
                validator=args.IndexValidator(self.model),
            ),
        )

    def build_query(self, committee_id=None, candidate_id=None, **kwargs):
        query = super().build_query(**kwargs)

        if committee_id is not None:
            query = query.filter_by(committee_id=committee_id)

        if candidate_id is not None:
            query = query.join(
                models.CandidateCommitteeLink
            ).filter(
                models.CandidateCommitteeLink.candidate_id == candidate_id
            ).distinct()

        if kwargs.get('year'):
            query = filter_year(models.CommitteeDetail, query, kwargs['year'])

        if kwargs.get('cycle'):
            query = query.filter(models.CommitteeDetail.cycles.overlap(kwargs['cycle']))

        return query


@doc(
    tags=['committee'],
    description=docs.COMMITTEE_HISTORY,
    params={
        'candidate_id': {'description': docs.CANDIDATE_ID},
        'committee_id': {'description': docs.COMMITTEE_ID},
        'cycle': {'description': docs.COMMITTEE_CYCLE},
    },
)
class CommitteeHistoryView(ApiResource):

    model = models.CommitteeHistory
    schema = schemas.CommitteeHistorySchema
    page_schema = schemas.CommitteeHistoryPageSchema

    @property
    def args(self):
        return utils.extend(
            args.paging,
            args.committee_history,
            args.make_sort_args(
                default='-cycle',
                validator=args.IndexValidator(self.model),
            ),
        )

    def build_query(self, committee_id=None, candidate_id=None, cycle=None, **kwargs):
        query = models.CommitteeHistory.query

        if committee_id:
            query = query.filter(models.CommitteeHistory.committee_id == committee_id)

        if candidate_id:
            query = query.join(
                models.CandidateCommitteeLink,
                sa.and_(
                    models.CandidateCommitteeLink.committee_id == models.CommitteeHistory.committee_id,
                    models.CandidateCommitteeLink.fec_election_year == models.CommitteeHistory.cycle,
                ),
            ).filter(
                models.CandidateCommitteeLink.candidate_id == candidate_id,
            ).distinct()

        if cycle:
            query = (
                self._filter_elections(query, candidate_id, cycle)
                if kwargs.get('election_full') and candidate_id
                else query.filter(models.CommitteeHistory.cycle == cycle)
            )

        return query

    def _filter_elections(self, query, candidate_id, cycle):
        election_duration = utils.get_election_duration(models.CandidateCommitteeLink.committee_type)
        return query.join(
            models.CandidateElection,
            sa.and_(
                models.CandidateCommitteeLink.candidate_id == models.CandidateElection.candidate_id,
                models.CandidateCommitteeLink.fec_election_year > models.CandidateElection.cand_election_year - election_duration,
                models.CandidateCommitteeLink.fec_election_year <= models.CandidateElection.cand_election_year,
            ),
        ).filter(
            models.CandidateElection.candidate_id == candidate_id,
            models.CandidateElection.cand_election_year >= cycle,
            models.CandidateElection.cand_election_year < cycle + election_duration,
        ).order_by(
            models.CommitteeHistory.committee_id,
            sa.desc(models.CommitteeHistory.cycle),
        ).distinct(
            models.CommitteeHistory.committee_id,
        )
