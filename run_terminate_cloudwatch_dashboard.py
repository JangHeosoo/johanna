#!/usr/bin/env python3

from env import env
from run_common import AWSCli
from run_common import print_message
from run_common import print_session

if __name__ == "__main__":
    from run_common import parse_args

    parse_args()


def run_terminate_cloudwatch_dashboard(name, settings):
    region = settings['AWS_DEFAULT_REGION']
    aws_cli = AWSCli(region)

    dashboard_name = '%s_%s' % (name, region)
    print_message('terminate cloudwatch dashboard: %s' % dashboard_name)

    cmd = ['cloudwatch', 'delete-dashboards']
    cmd += ['--dashboard-names', dashboard_name]
    aws_cli.run(cmd)


################################################################################
#
# start
#
################################################################################
print_session('terminate cloudwatch dashboard')

cw = env.get('cloudwatch', dict())
cw_dashboards_list = cw.get('DASHBOARDS', list())
for cw_dashboard_env in cw_dashboards_list:
    run_terminate_cloudwatch_dashboard(cw_dashboard_env['NAME'], cw_dashboard_env)
