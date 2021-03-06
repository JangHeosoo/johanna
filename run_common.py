#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
import time
from optparse import OptionParser

from env import env

try:
    # noinspection PyShadowingBuiltins, PyUnresolvedReferences
    input = raw_input
except NameError:
    pass


def _confirm_phase():
    phase = env['common']['PHASE']
    service_name = env['common'].get('SERVICE_NAME', '(none)')
    print('Your current environment values are below')
    print('-' * 80)
    print('\tSERVICE_NAME        : %s' % service_name)
    print('\tPHASE               : %s' % phase)
    if 'template' in env:
        print('\tTEMPLATE            : %s' % env['template']['NAME'])
    if 'elasticbeanstalk' in env:
        eb = env['elasticbeanstalk']
        for eb_env in eb['ENVIRONMENTS']:
            aws_default_region = env['aws']['AWS_DEFAULT_REGION'] \
                if 'AWS_DEFAULT_REGION' not in eb_env \
                else eb_env['AWS_DEFAULT_REGION']
            print('\tCNAME of %-10s : %-20s (%s)' % (eb_env['NAME'], eb_env['CNAME'], aws_default_region))
    print('-' * 80)

    answer = input('Please type in the name of phase \'%s\' to confirm: ' % phase)
    if answer != phase:
        print('The execution is canceled.')
        sys.exit(0)


class AWSCli:
    cidr_vpc = dict()
    cidr_vpc['rds'] = env['common']['AWS_VPC_RDS']
    cidr_vpc['eb'] = env['common']['AWS_VPC_EB']

    cidr_subnet = dict()
    cidr_subnet['rds'] = dict()
    cidr_subnet['rds']['private_1'] = env['common']['AWS_SUBNET_RDS_PRIVATE_1']
    cidr_subnet['rds']['private_2'] = env['common']['AWS_SUBNET_RDS_PRIVATE_2']
    cidr_subnet['eb'] = dict()
    cidr_subnet['eb']['private_1'] = env['common']['AWS_SUBNET_EB_PRIVATE_1']
    cidr_subnet['eb']['private_2'] = env['common']['AWS_SUBNET_EB_PRIVATE_2']
    cidr_subnet['eb']['public_1'] = env['common']['AWS_SUBNET_EB_PUBLIC_1']
    cidr_subnet['eb']['public_2'] = env['common']['AWS_SUBNET_EB_PUBLIC_2']

    def __init__(self, aws_default_region=None):
        if not env['aws'].get('AWS_ACCESS_KEY_ID') or \
                not env['aws'].get('AWS_SECRET_ACCESS_KEY') or \
                not env['aws'].get('AWS_DEFAULT_REGION'):
            raise Exception()

        self.env = dict(os.environ)
        self.env['AWS_ACCESS_KEY_ID'] = env['aws']['AWS_ACCESS_KEY_ID']
        self.env['AWS_SECRET_ACCESS_KEY'] = env['aws']['AWS_SECRET_ACCESS_KEY']
        self.env['AWS_DEFAULT_REGION'] = env['aws']['AWS_DEFAULT_REGION'] \
            if not aws_default_region \
            else aws_default_region

    def run(self, args, cwd=None, ignore_error=None):
        args = ['aws'] + args
        if ignore_error:
            print('\n>> command(ignore error): [%s]' % self.env['AWS_DEFAULT_REGION'], end=" ")
        else:
            print('\n>> command: [%s]' % self.env['AWS_DEFAULT_REGION'], end=" ")
        print(' '.join(args))
        _p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              cwd=cwd, env=self.env)
        result, error = _p.communicate()
        # noinspection PyUnresolvedReferences
        result = result.decode('utf-8')

        if error:
            print(error.decode('utf-8'))
            if not ignore_error:
                raise Exception()

        if _p.returncode != 0:
            print('command returns: %s' % _p.returncode)
            if not ignore_error:
                raise Exception()

        if args[0] == 'aws':
            # noinspection PyBroadException
            try:
                return json.loads(result)
            except Exception:
                return result
        elif args[0] == 'eb':
            return result

        return dict()

    def get_vpc_id(self):
        rds_vpc_id = None
        cmd = ['ec2', 'describe-vpcs']
        cmd += ['--filters=Name=cidr,Values=%s' % self.cidr_vpc['rds']]
        result = self.run(cmd)
        if len(result['Vpcs']) == 1:
            rds_vpc_id = dict(result['Vpcs'][0])['VpcId']

        eb_vpc_id = None
        cmd = ['ec2', 'describe-vpcs']
        cmd += ['--filters=Name=cidr,Values=%s' % self.cidr_vpc['eb']]
        result = self.run(cmd)
        if len(result['Vpcs']) == 1:
            eb_vpc_id = dict(result['Vpcs'][0])['VpcId']

        return rds_vpc_id, eb_vpc_id

    def get_elasticache_address(self):
        cmd = ['elasticache', 'describe-cache-clusters', '--show-cache-node-info']

        elapsed_time = 0
        cache_address = None
        while not cache_address:
            result = self.run(cmd)

            # noinspection PyBroadException
            try:
                cache_clusters = result['CacheClusters'][0]
                cache_nodes = dict(cache_clusters)['CacheNodes'][0]
                cache_endpoint = dict(cache_nodes)['Endpoint']
                cache_address = dict(cache_endpoint)['Address']
                if cache_address:
                    return cache_address
            except Exception:
                pass

            print('waiting for a new cache... (elapsed time: \'%d\' seconds)' % elapsed_time)
            time.sleep(5)
            elapsed_time += 5

            if elapsed_time > 60 * 30:
                raise Exception()

    def get_rds_address(self, read_replica=None):
        engine = env['rds']['ENGINE']
        if engine == 'aurora':
            cmd = ['rds', 'describe-db-clusters']

            elapsed_time = 0
            db_address = None
            while not db_address:
                result = self.run(cmd)

                # noinspection PyBroadException
                try:
                    for db_cluster in result['DBClusters']:
                        db_cluster = dict(db_cluster)

                        if db_cluster['Status'] != 'available':
                            continue

                        if read_replica and 'ReaderEndpoint' not in db_cluster:
                            continue

                        db_endpoint = db_cluster['Endpoint']

                        if read_replica:
                            db_endpoint = db_cluster['ReaderEndpoint']

                        if db_endpoint:
                            return db_endpoint
                except Exception:
                    pass

                print('waiting for a new database... (elapsed time: \'%d\' seconds)' % elapsed_time)
                time.sleep(5)
                elapsed_time += 5

                if elapsed_time > 60 * 30:
                    raise Exception()
        else:
            cmd = ['rds', 'describe-db-instances']

            elapsed_time = 0
            db_address = None
            while not db_address:
                result = self.run(cmd)

                # noinspection PyBroadException
                try:
                    for db_cluster in result['DBInstances']:
                        db_cluster = dict(db_cluster)

                        if not read_replica and 'ReadReplicaSourceDBInstanceIdentifier' in db_cluster:
                            continue
                        elif read_replica and 'ReadReplicaSourceDBInstanceIdentifier' not in db_cluster:
                            continue

                        db_endpoint = db_cluster['Endpoint']
                        db_address = dict(db_endpoint)['Address']

                        if db_address:
                            return db_address
                except Exception:
                    pass

                print('waiting for a new database... (elapsed time: \'%d\' seconds)' % elapsed_time)
                time.sleep(5)
                elapsed_time += 5

                if elapsed_time > 60 * 30:
                    raise Exception()

    def get_role_arn(self, role_name):
        cmd = ['iam', 'get-role']
        cmd += ['--role-name', role_name]
        result = self.run(cmd)

        # noinspection PyTypeChecker
        return result['Role']['Arn']

    def get_topic_arn(self, topic_name):
        cmd = ['sns', 'list-topics']
        result = self.run(cmd)

        for topic in result['Topics']:
            suffix = ':%s' % topic_name
            # noinspection PyTypeChecker
            arn = topic['TopicArn']
            if arn.endswith(suffix):
                return arn

        return

    def get_temp_bucket(self):
        default_region = env['aws']['AWS_DEFAULT_REGION']

        cmd = ['s3api', 'list-buckets']

        result = self.run(cmd)
        for bucket in result['Buckets']:
            bucket = dict(bucket)

            pattern = 'johanna-%s-[0-9]+' % default_region
            name = bucket['Name']
            if re.match(pattern, name):
                return name

        timestamp = int(time.time())
        bucket_name = 'johanna-%s-%s' % (default_region, timestamp)

        cmd = ['s3api', 'create-bucket', '--bucket', bucket_name, '--region', default_region,
               '--create-bucket-configuration', 'LocationConstraint=%s' % default_region]
        self.run(cmd)

        cmd = ['s3api', 'head-bucket', '--bucket', bucket_name]

        elapsed_time = 0
        while True:
            result = self.run(cmd)

            if len(result) == 0:
                break

            print('creating bucket... (elapsed time: \'%d\' seconds)' % elapsed_time)
            time.sleep(5)
            elapsed_time += 5

        return bucket_name

    def get_iam_role(self, role_name):
        cmd = ['iam', 'get-role']
        cmd += ['--role-name', role_name]
        return self.run(cmd, ignore_error=True)

    def get_iam_role_policy(self, role_name, policy_name):
        cmd = ['iam', 'get-role-policy']
        cmd += ['--role-name', role_name]
        cmd += ['--policy-name', policy_name]
        return self.run(cmd, ignore_error=True)

    def set_name_tag(self, resource_id, name):
        cmd = ['ec2', 'create-tags']
        cmd += ['--resources', resource_id]
        cmd += ['--tags', 'Key=Name,Value=%s' % name]
        self.run(cmd)

    def wait_terminate_lambda(self):
        cmd = ['lambda', 'list-functions']

        elapsed_time = 0
        while True:
            result = self.run(cmd)
            if len(result['Functions']) == 0:
                break

            print('terminating the lambda... (elapsed time: \'%d\' seconds)' % elapsed_time)
            time.sleep(5)
            elapsed_time += 5

    def wait_terminate_rds(self):
        cmd = ['rds', 'describe-db-instances']

        elapsed_time = 0
        while True:
            result = self.run(cmd)
            if len(result['DBInstances']) == 0:
                break

            print('terminating the rds... (elapsed time: \'%d\' seconds)' % elapsed_time)
            time.sleep(5)
            elapsed_time += 5

        cmd = ['rds', 'describe-db-clusters']

        while True:
            result = self.run(cmd)
            if len(result['DBClusters']) == 0:
                break

            print('terminating the rds... (elapsed time: \'%d\' seconds)' % elapsed_time)
            time.sleep(5)
            elapsed_time += 5

    def wait_terminate_elasticache(self):
        cmd = ['elasticache', 'describe-cache-clusters']

        elapsed_time = 0
        while True:
            result = self.run(cmd)
            if len(result['CacheClusters']) == 0:
                break

            print('terminating the elasticache... (elapsed time: \'%d\' seconds)' % elapsed_time)
            time.sleep(5)
            elapsed_time += 5

    def wait_terminate_eb(self):
        cmd = ['ec2', 'describe-instances']

        elapsed_time = 0
        while True:
            result = self.run(cmd)
            count = 0
            for r in result['Reservations']:
                for instance in r.get('Instances'):
                    if instance['State']['Name'] != 'terminated':
                        count += 1

            if count == 0:
                break

            print('terminating the eb... (elapsed time: \'%d\' seconds)' % elapsed_time)
            time.sleep(5)
            elapsed_time += 5

    def wait_create_nat_gateway(self, eb_vpc_id=None):
        cmd = ['ec2', 'describe-nat-gateways']

        elapsed_time = 0
        while True:
            result = self.run(cmd)
            count = 0
            for r in result['NatGateways']:
                if eb_vpc_id and r.get('VpcId') != eb_vpc_id:
                    continue
                if r.get('State') != 'available':
                    count += 1

            if count == 0:
                break

            print('waiting for a new nat gateway... (elapsed time: \'%d\' seconds)' % elapsed_time)
            time.sleep(5)
            elapsed_time += 5

    def wait_delete_nat_gateway(self, eb_vpc_id=None):
        cmd = ['ec2', 'describe-nat-gateways']

        elapsed_time = 0
        while True:
            result = self.run(cmd)
            count = 0
            for r in result['NatGateways']:
                if eb_vpc_id and r.get('VpcId') != eb_vpc_id:
                    continue
                if r.get('State') != 'deleted':
                    count += 1

            if count == 0:
                break

            print('deleting the nat gateway... (elapsed time: \'%d\' seconds)' % elapsed_time)
            time.sleep(5)
            elapsed_time += 5


def parse_args(require_arg=False):
    if require_arg:
        usage = 'usage: %prog [options] arg'
    else:
        usage = 'usage: %prog [options]'

    parser = OptionParser(usage=usage)
    parser.add_option("-f", "--force", action="store_true", help='skip the phase confirm')
    (options, args) = parser.parse_args(sys.argv)

    if not options.force:
        _confirm_phase()

    return args


def print_message(message):
    print('*' * 80)
    print(message + '\n')


def print_session(message):
    print('\n' + '#' * 80 + '\n' + '#' * 80)
    print('\n\t[ ' + message + ' ]\n\n')


def read_file(file_path):
    f = open(file_path)
    lines = list()
    for ll in f.readlines():
        lines.append(ll)
    f.close()

    return lines


def write_file(file_path, lines):
    f = open(file_path, 'w')
    for ll in lines:
        f.write(ll)
    f.close()


def re_sub_lines(lines, pattern, repl):
    new_lines = list()
    for ll in lines:
        ll = re.sub(pattern, repl, ll)
        new_lines.append(ll)

    return new_lines


def check_template_availability():
    if 'template' not in env:
        print('template is not defined in config.json')
        raise Exception()

    if 'NAME' not in env['template']:
        print('template.NAME is not defined in config.json')
        raise Exception()

    if not os.path.exists('template/%s' % env['template']['NAME']):
        print('template: %s is not downloaded. please run: ./run.py reset_template.' % env['template']['NAME'])
        raise Exception()
