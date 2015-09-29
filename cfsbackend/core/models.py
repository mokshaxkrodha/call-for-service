# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
#
# Also note: You'll have to insert the output of 'django-admin sqlcustom [app_label]'
# into your database.

from __future__ import unicode_literals
from collections import Counter
from datetime import timedelta

from django.db import models, connection
from django.db.models import Count, Aggregate, DurationField, Min, Max, \
    IntegerField, Sum, Case, When, F
from django.db.models.expressions import Func


def dictfetchall(cursor):
    "Returns all rows from a cursor as a dict"
    desc = cursor.description
    return [
        dict(zip([col[0] for col in desc], row))
        for row in cursor.fetchall()
        ]


class DateTrunc(Func):
    """
    Truncates a timestamp. Useful for investigating time series.

    The `by` named parameter can take:

    * microseconds
    * milliseconds
    * second
    * minute
    * hour
    * day
    * week
    * month
    * quarter
    * year
    * decade
    * century
    * millennium
    """

    function = "DATE_TRUNC"
    template = "%(function)s('%(by)s', %(expressions)s)"

    def __init__(self, expression, **extra):
        self.expression = expression
        try:
            self.by = extra['by']
        except KeyError:
            raise ValueError("by named argument must be specified")
        super().__init__(expression, **extra)


class DurationAvg(Aggregate):
    function = 'AVG'
    name = 'Avg'

    def __init__(self, expression, **extra):
        super().__init__(expression, output_field=DurationField(), **extra)

    def convert_value(self, value, expression, connection, context):
        if value is not None:
            return value.total_seconds()


class CallOverview:
    def __init__(self, filters):
        from .filters import CallFilter
        self.filter = CallFilter(filters, queryset=Call.objects.all())
        self.bounds = self.qs.aggregate(min_time=Min('time_received'),
                                        max_time=Max('time_received'))
        if self.bounds['max_time'] and self.bounds['min_time']:
            self.span = self.bounds['max_time'] - self.bounds['min_time']
        else:
            self.span = timedelta(0, 0)

    @property
    def qs(self):
        return self.filter.qs

    def volume_by_field(self, field, alias=None):
        if alias:
            qs = self.qs.annotate(**{alias: F(field)}).values(alias)
            field = alias
        else:
            qs = self.qs.values(field)

        return qs.annotate(volume=Count(field))

    def volume_over_time(self):
        if self.span >= timedelta(180):
            size = 'month'
        elif self.span > timedelta(3):
            size = 'day'
        else:
            size = 'hour'

        results = self.qs.annotate(
            period_start=DateTrunc('time_received', by=size)) \
            .values('period_start') \
            .annotate(period_volume=Count('period_start')) \
            .order_by('period_start')

        return {
            'bounds': self.bounds,
            'period_size': size,
            'results': results
        }

    def rolling_average(self):
        cursor = connection.cursor()

        cte_sql, params = self.qs. \
            annotate(date_received=DateTrunc('time_received', by='day')). \
            values('date_received'). \
            annotate(call_volume=Count('date_received')).query.sql_with_params()
        sql = """
        WITH daily_stats AS (
            {cte_sql}
        )
        SELECT
            ds1.date_received AS date_received,
            ds1.call_volume AS call_volume,
            CAST(AVG(ds2.call_volume) AS INTEGER) AS call_volume_moving_average
        FROM daily_stats AS ds1
        JOIN daily_stats AS ds2
            ON ds2.date_received BETWEEN ds1.date_received - INTERVAL '15 days' AND
            ds1.date_received + INTERVAL '15 days'
        GROUP BY ds1.date_received, ds1.call_volume;
        """.format(cte_sql=cte_sql)

        cursor.execute(sql, params)
        results = dictfetchall(cursor)
        return results

    def day_hour_heatmap(self):
        if self.span == timedelta(0, 0):
            return []

        # In order for this to show average volume, we need to know the number 
        # of times each day of the week occurs.
        start = self.bounds['min_time'].date()
        end = self.bounds['max_time'].date()
        weekdays = Counter((start + timedelta(days=x)).weekday() for x in
                           range(0, (end - start).days + 1))

        results = self.qs \
            .values('dow_received', 'hour_received') \
            .annotate(volume=Count('dow_received')) \
            .order_by('dow_received', 'hour_received')

        for result in results:
            result['freq'] = weekdays[result['dow_received']]
            result['total'] = result['volume']
            result['volume'] /= result['freq']

        return results

    def response_time_by_beat(self):
        results = self.qs \
            .values("beat", "beat__descr") \
            .annotate(mean=DurationAvg("response_time"),
                      missing=Sum(Case(When(response_time=None, then=1),
                                       default=0,
                                       output_field=IntegerField())))
        return results

    def to_dict(self):
        return {
            'filter': self.filter.data,
            'volume_over_time': self.volume_over_time(),
            'volume_rolling_average': self.rolling_average(),
            'day_hour_heatmap': self.day_hour_heatmap(),
            'volume_by_source': self.volume_by_field('call_source__descr',
                                                     alias="name"),
            'volume_by_nature': self.volume_by_field('nature__descr',
                                                     alias="name"),
            'volume_by_beat': self.volume_by_field('beat__descr', alias="name"),
            'response_time_by_beat': self.response_time_by_beat()
        }


class ModelWithDescr(models.Model):
    descr = models.TextField(blank=False, null=False)

    def __str__(self):
        if self.descr:
            return self.descr
        else:
            return super().__str__()

    class Meta:
        abstract = True
        ordering = ['descr']


class Sector(ModelWithDescr):
    sector_id = models.IntegerField(primary_key=True)

    class Meta:
        managed = False
        db_table = 'sector'


class District(ModelWithDescr):
    district_id = models.IntegerField(primary_key=True)
    sector = models.ForeignKey(Sector, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'district'


class Beat(ModelWithDescr):
    beat_id = models.IntegerField(primary_key=True)
    district = models.ForeignKey(District, blank=True, null=True)
    sector = models.ForeignKey(Sector, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'beat'


class CallSource(ModelWithDescr):
    call_source_id = models.IntegerField(primary_key=True)

    class Meta:
        managed = False
        db_table = 'call_source'


class City(ModelWithDescr):
    city_id = models.IntegerField(primary_key=True)

    class Meta:
        managed = False
        db_table = 'city'


class CallUnit(ModelWithDescr):
    call_unit_id = models.IntegerField(primary_key=True)

    class Meta:
        managed = False
        db_table = 'call_unit'


class Nature(ModelWithDescr):
    nature_id = models.IntegerField(primary_key=True)

    class Meta:
        managed = False
        db_table = 'nature'


class CloseCode(ModelWithDescr):
    close_code_id = models.IntegerField(primary_key=True)

    class Meta:
        managed = False
        db_table = 'close_code'


class OOSCode(ModelWithDescr):
    oos_code_id = models.IntegerField(primary_key=True)

    class Meta:
        managed = False
        db_table = 'oos_code'


class OutOfServicePeriods(models.Model):
    oos_id = models.IntegerField(primary_key=True)
    call_unit = models.ForeignKey(CallUnit, blank=True, null=True,
                                  db_column="call_unit_id",
                                  related_name="call_unit")
    shift_unit_id = models.BigIntegerField(blank=True, null=True)
    oos_code = models.ForeignKey(OOSCode, blank=True, null=True,
                                 db_column="oos_code_id",
                                 related_name="oos_code")
    location = models.TextField(blank=True, null=True)
    comments = models.TextField(blank=True, null=True)
    start_time = models.DateTimeField(blank=True, null=True)
    end_time = models.DateTimeField(blank=True, null=True)
    duration = models.DurationField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'out_of_service'


# Primary Classes

class Call(models.Model):
    call_id = models.BigIntegerField(primary_key=True)
    year_received = models.IntegerField(blank=True, null=True)
    month_received = models.IntegerField(blank=True, null=True)
    week_received = models.IntegerField(blank=True, null=True)
    dow_received = models.IntegerField(blank=True, null=True)
    hour_received = models.IntegerField(blank=True, null=True)
    case_id = models.BigIntegerField(blank=True, null=True)
    call_source = models.ForeignKey('CallSource', blank=True, null=True)
    primary_unit = models.ForeignKey(CallUnit, blank=True, null=True,
                                     related_name="+")
    first_dispatched = models.ForeignKey(CallUnit, blank=True, null=True,
                                         related_name="+")
    reporting_unit = models.ForeignKey(CallUnit, blank=True, null=True,
                                       related_name="+")
    street_num = models.IntegerField(blank=True, null=True)
    street_name = models.TextField(blank=True, null=True)
    city = models.ForeignKey('City', blank=True, null=True)
    zip_code = models.ForeignKey('ZipCode', blank=True, null=True)
    crossroad1 = models.TextField(blank=True, null=True)
    crossroad2 = models.TextField(blank=True, null=True)
    geox = models.FloatField(blank=True, null=True)
    geoy = models.FloatField(blank=True, null=True)
    beat = models.ForeignKey(Beat, blank=True, null=True)
    district = models.ForeignKey('District', blank=True, null=True)
    sector = models.ForeignKey('Sector', blank=True, null=True)
    business = models.TextField(blank=True, null=True)
    nature = models.ForeignKey('Nature', blank=True, null=True)
    priority = models.ForeignKey('Priority', blank=True, null=True)
    report_only = models.NullBooleanField()
    cancelled = models.NullBooleanField()
    time_received = models.DateTimeField(blank=True, null=True)
    time_routed = models.DateTimeField(blank=True, null=True)
    time_finished = models.DateTimeField(blank=True, null=True)
    first_unit_dispatch = models.DateTimeField(blank=True, null=True)
    first_unit_enroute = models.DateTimeField(blank=True, null=True)
    first_unit_arrive = models.DateTimeField(blank=True, null=True)
    first_unit_transport = models.DateTimeField(blank=True, null=True)
    last_unit_clear = models.DateTimeField(blank=True, null=True)
    time_closed = models.DateTimeField(blank=True, null=True)
    close_code = models.ForeignKey('CloseCode', blank=True, null=True)
    close_comments = models.TextField(blank=True, null=True)
    incident = models.ForeignKey('Incident', blank=True, null=True)
    response_time = models.DurationField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'call'


class Incident(models.Model):
    incident_id = models.BigIntegerField(primary_key=True)
    case_id = models.BigIntegerField(unique=True, blank=True, null=True)
    time_filed = models.DateTimeField(blank=True, null=True)
    month_filed = models.IntegerField(blank=True, null=True)
    week_filed = models.IntegerField(blank=True, null=True)
    dow_filed = models.IntegerField(blank=True, null=True)
    street_num = models.IntegerField(blank=True, null=True)
    street_name = models.TextField(blank=True, null=True)
    city = models.ForeignKey(City, blank=True, null=True)
    # zip_code = models.ForeignKey('ZipCode', blank=True, null=True)
    # zipcode     = models.IntegerField(blank=True, null=True, db_column="zip")
    geox = models.FloatField(blank=True, null=True)
    geoy = models.FloatField(blank=True, null=True)
    beat = models.ForeignKey(Beat, blank=True, null=True)
    district = models.ForeignKey(District, blank=True, null=True)
    sector = models.ForeignKey(Sector, blank=True, null=True)
    # premise    = models.ForeignKey('Premise', blank=True, null=True)
    # weapon     = models.ForeignKey('Weapon', blank=True, null=True)
    domestic = models.NullBooleanField()
    juvenile = models.NullBooleanField()
    gang_related = models.NullBooleanField()
    # emp_bureau = models.ForeignKey(Bureau, blank=True, null=True)
    # emp_division = models.ForeignKey(Division, blank=True, null=True)
    # emp_unit = models.ForeignKey('Unit', blank=True, null=True)
    num_officers = models.IntegerField(blank=True, null=True)
    # investigation_status = models.ForeignKey('InvestigationStatus', blank=True, null=True)
    # investigator_unit = models.ForeignKey('Unit', blank=True, null=True)
    # case_status = models.ForeignKey(CaseStatus, blank=True, null=True)
    # ucr_code = models.IntegerField(blank=True, null=True)
    # ucr_descr = models.ForeignKey('UcrDescr', blank=True, null=True)
    committed = models.NullBooleanField()

    class Meta:
        managed = False
        db_table = 'incident'


class Priority(ModelWithDescr):
    priority_id = models.IntegerField(primary_key=True)

    class Meta:
        managed = False
        db_table = 'priority'


class ZipCode(ModelWithDescr):
    zip_code_id = models.IntegerField(primary_key=True)

    class Meta:
        managed = False
        db_table = 'zip_code'
