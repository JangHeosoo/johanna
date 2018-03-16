#!/usr/bin/env python3

from env import env
from run_common import AWSCli
from run_common import print_message
from run_common import print_session

if __name__ == "__main__":
    from run_common import parse_args

    parse_args()


def run_create_cloudwatch_alarm_elasticbeanstalk(name, settings):
    region = settings['AWS_DEFAULT_REGION']
    aws_cli = AWSCli(region)

    print_message('get elasticbeanstalk environment info: %s' % name)

    cmd = ['elasticbeanstalk', 'describe-environments']
    cmd += ['--no-include-deleted']
    result = aws_cli.run(cmd)

    env_list = list()
    for ee in result['Environments']:
        cname = ee['CNAME']
        if not cname.endswith('%s.%s.elasticbeanstalk.com' % (name, region)):
            continue
        ename = ee['EnvironmentName']
        if ename.startswith(name):
            env_list.append(ee)

    env_instances_list = list()

    for ee in env_list:
        cmd = ['elasticbeanstalk', 'describe-environment-resources']
        cmd += ['--environment-id', ee['EnvironmentId']]
        result = aws_cli.run(cmd)
        ee_res = result['EnvironmentResources']
        for instance in ee_res['Instances']:
            ii = dict()
            ii['Id'] = instance['Id']
            ii['EnvironmentName'] = ee_res['EnvironmentName']
            env_instances_list.append(ii)

    ################################################################################
    alarm_name = '%s_%s_%s' % (name, region, settings['METRIC_NAME'])
    print_message('create or update cloudwatch alarm: %s' % alarm_name)

    topic_arn = aws_cli.get_topic_arn(settings['SNS_TOPIC_NAME'])
    if not topic_arn:
        raise Exception()

    dimension_list = list()
    for ei in env_instances_list:
        if settings['DIMENSIONS'] == 'InstanceId':
            dimension = 'Name=InstanceId,Value=%s' % ei['Id']
            dimension_list.append(dimension)
        if settings['DIMENSIONS'] == 'EnvironmentName':
            dimension = 'Name=EnvironmentName,Value=%s' % ei['EnvironmentName']
            dimension_list.append(dimension)
            break

    cmd = ['cloudwatch', 'put-metric-alarm']
    cmd += ['--alarm-name', alarm_name]
    cmd += ['--alarm-description', settings['DESCRIPTION']]
    cmd += ['--namespace', settings['NAMESPACE']]
    cmd += ['--metric-name', settings['METRIC_NAME']]
    cmd += ['--statistic', settings['STATISTIC']]
    cmd += ['--period', settings['PERIOD']]
    cmd += ['--threshold', settings['THRESHOLD']]
    cmd += ['--comparison-operator', settings['COMPARISON_OPERATOR']]
    cmd += ['--dimensions', ' '.join(dimension_list)]
    cmd += ['--evaluation-periods', settings['EVALUATION_PERIODS']]
    cmd += ['--alarm-actions', topic_arn]
    aws_cli.run(cmd)


################################################################################
#
# start
#
################################################################################
print_session('create cloudwatch alarm')

cw = env['cloudwatch']
cw_alarms = cw['ALARMS']
for ca in cw_alarms:
    if ca['TYPE'] == 'elasticbeanstalk':
        run_create_cloudwatch_alarm_elasticbeanstalk(ca['NAME'], ca)