#!/usr/bin/env python3
"""Prometheus service discovery for Docker Swarm"""
import argparse
import json
import logging
from time import sleep
from pprint import pformat
import docker

# Default settings
DEFAULT_PATH = '/etc/prometheus/swarm.d/swarm-endpoints.json'
DEFAULT_LABEL_NAME = 'prometheus.port'
DEFAULT_ENV_NAME = 'SERVICE_PORTS'
DEFAULT_SERVICE_NAME = 'prometheus'
DEFAULT_PCNETWORKS = ['proxy']

class PrometheusSwarmer(object):
    """PrometheusSwarmer scans for swarm services and generates prometheus config."""

    # pylint: disable=too-many-instance-attributes

    def __init__(self,
                 outputpath=DEFAULT_PATH,
                 label_name=DEFAULT_LABEL_NAME,
                 env_name=DEFAULT_ENV_NAME,
                 service_name=DEFAULT_SERVICE_NAME,
                 pcnetworks=None,
                 log=logging
                ):
        """Create a PrometheusSwarmer

        outputpath - The path to output the configuration to
        label_name - Service label to identify metrics port
        env_name - Environment variable to identify metrics port
        service_name - The name of the prometheus service
        pcnetworks - Override prometheus service detection with a static network list
        """

        # pylint: disable=too-many-arguments

        self.log = log
        self.outputpath = outputpath
        self.label_name = label_name
        self.env_name = env_name
        self.service_name = service_name

        self.client = docker.from_env()

        # Find which networks the prometheus service is on
        if pcnetworks is None:
            try:
                pcnetworks = []
                pservice = self.client.services.get(service_name)
                ptask = pservice.tasks()[0]
                for netattachment in ptask['NetworksAttachments']:
                    pcnetworks.append(netattachment['Network']['Spec']['Name'])
                self.log.debug("Discovered networks: %s", pcnetworks)
            except docker.errors.NotFound:
                self.log.debug("Prometheus container not found, using default networks")
                pcnetworks = DEFAULT_PCNETWORKS
            except KeyError:
                self.log.debug("Prometheus container is not on any networks, using defaults")
                pcnetworks = DEFAULT_PCNETWORKS

        self.pcnetworks = pcnetworks

        self.endpoints = []

    def discover(self):
        """Discover the services exposing metrics endpoints"""

        # pylint: disable=too-many-branches

        self.endpoints = []
        for service in self.client.services.list():
            name = service.attrs['Spec']['Name']

            # Don't monitor prometheus itself (it can do that)
            if name == self.service_name:
                continue

            # Service labels
            slabels = service.attrs['Spec']['Labels'] if 'Labels' in service.attrs['Spec'] \
                    else {}

            # Container labels
            cspec = service.attrs['Spec']['TaskTemplate']['ContainerSpec']
            clabels = cspec['Labels'] if 'Labels' in cspec else {}

            # Skip services labelled with 'nometrics'
            if 'nometrics' in slabels or 'nometrics' in clabels:
                self.log.debug("Service '%s' has a 'nometrics' label, skipping", name)
                continue

            # Environment variables
            envs = cspec['Env'] if 'Env' in cspec else []

            port = None
            if self.label_name in slabels:
                port = slabels[self.label_name]
            else:
                ports = [x.split('=')[1] for x in envs if x.startswith(self.env_name + '=')]
                if len(ports) == 1:
                    # Support a comma-separated list - take the first
                    port = ports[0].split(',')[0]
            if port is None:
                self.log.debug("Unable to find port for service '%s', skipping", name)
                continue

            for task in service.tasks():
                # Skip tasks for containers that the service manager doesn't run anymore
                if task['DesiredState'] != 'running':
                    continue

                if 'NetworksAttachments' not in task:
                    self.log.debug("Task for service '%s' on no networks, skipping", name)
                    continue

                # Add an endpoint for the first matching network
                for network in task['NetworksAttachments']:
                    if network['Network']['Spec']['Name'] not in self.pcnetworks:
                        continue
                    address = network['Addresses'][0].split('/')[0]
                    endpoint = {
                        'targets': [address + ':' + port],
                        'labels': {
                            'job': name
                        }
                    }
                    for label in slabels:
                        legallabel = label.replace('.', '_')
                        endpoint['labels']['service_label_{}'.format(legallabel)] = \
                                slabels[label]
                    for label in clabels:
                        legallabel = label.replace('.', '_')
                        endpoint['labels']['container_label_{}'.format(legallabel)] \
                                = clabels[label]
                    try:
                        endpoint['labels']['container_id'] = \
                            task['Status']['ContainerStatus']['ContainerID']
                    except KeyError:
                        pass
                    # Support a custom metrics path
                    if 'PROM_METRICS_PATH' in envs:
                        endpoint['labels']['__metrics_path__'] = envs['PROM_METRICS_PATH']
                    self.endpoints.append(endpoint)
                    self.log.debug('Add endpoint for %s at %s:%s', name, address, port)
                    break

        self.log.debug(pformat(self.endpoints))


    def writejson(self):
        """Write the discovered endpoints to the config file"""
        with open(self.outputpath, "w") as jsonfile:
            json.dump(self.endpoints, jsonfile)

    def run(self):
        """Run discovery in an infinite loop"""
        self.log.info("In A.D. 2101 prometheus-swarmer was beginning.")
        while True:
            self.log.debug("Start discovery")
            self.discover()
            self.log.debug("Finish discovery")
            self.writejson()
            sleep(60)

def parse_args():
    """Handle command-line arguments"""

    parser = argparse.ArgumentParser(description='Discover Prometheus metrics endpoints in a swarm')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('-l', '--label', help='Service label to look for',
                        default=DEFAULT_LABEL_NAME)
    parser.add_argument('-e', '--env-name', help='Environment variable to look for',
                        default=DEFAULT_ENV_NAME)
    parser.add_argument('-o', '--output', help='Path to write output JSON to',
                        default=DEFAULT_PATH)
    parser.add_argument('-s', '--service', help='Name of prometheus service to detect',
                        default=DEFAULT_SERVICE_NAME)

    return parser.parse_args()


def main():
    """Main function for running class directly"""

    args = parse_args()

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG if args.debug else logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)

    sparams = {}
    sparams['outputpath'] = args.output
    sparams['label_name'] = args.label
    sparams['env_name'] = args.env_name
    sparams['service_name'] = args.service
    sparams['log'] = logger

    swarmer = PrometheusSwarmer(**sparams)
    swarmer.run()

if __name__ == '__main__':
    main()
