#!/usr/bin/env python3
"""Prometheus service discovery for Docker Swarm"""
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

log = logging.getLogger(__name__) # pylint: disable=invalid-name
logging.basicConfig(level=logging.DEBUG)

class PrometheusSwarmer(object):
    """PrometheusSwarmer scans for swarm services and generates prometheus config."""

    def __init__(self, # pylint: disable=too-many-arguments
                 outputpath=DEFAULT_PATH,
                 label_name=DEFAULT_LABEL_NAME,
                 env_name=DEFAULT_ENV_NAME,
                 service_name=DEFAULT_SERVICE_NAME,
                 pcnetworks=None,
                ):
        """Create a PrometheusSwarmer

        outputpath - The path to output the configuration to
        label_name - Service label to identify metrics port
        env_name - Environment variable to identify metrics port
        service_name - The name of the prometheus service
        pcnetworks - Override prometheus service detection with a static network list
        """

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
            except docker.errors.NotFound:
                pcnetworks = DEFAULT_PCNETWORKS
        self.pcnetworks = pcnetworks

        self.endpoints = []

    def discover(self): # pylint: disable=too-many-branches
        """Discover the services exposing metrics endpoints"""
        self.endpoints = []
        for service in self.client.services.list():
            name = service.attrs['Spec']['Name']

            # Don't monitor prometheus itself (it can do that)
            if name == self.service_name:
                continue

            # Service labels
            slabels = service.attrs['Spec']['Labels']

            # Container labels
            cspec = service.attrs['Spec']['TaskTemplate']['ContainerSpec']
            clabels = cspec['Labels'] if 'Labels' in cspec else {}

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
                log.debug("Unable to find port for service '%s', skipping", name)
                continue

            for task in service.tasks():
                # Skip tasks for containers that the service manager doesn't run anymore
                if task['DesiredState'] != 'running':
                    continue

                # Add an endpoint for the first matching network
                if 'NetworksAttachments' not in task:
                    log.debug("No network attachments for service '%s', skipping", name)
                    continue
                for network in task['NetworksAttachments']:
                    if network['Network']['Spec']['Name'] in self.pcnetworks:
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
                        self.endpoints.append(endpoint)
                        log.debug('Add endpoint for %s at %s:%s', name, address, port)
                        break

        log.debug(pformat(self.endpoints))


    def writejson(self):
        """Write the discovered endpoints to the config file"""
        with open(self.outputpath, "w") as jsonfile:
            json.dump(self.endpoints, jsonfile)

    def run(self):
        """Run discovery in an infinite loop"""
        log.info("In A.D. 2101 prometheus-swarmer was beginning.")
        while True:
            log.debug("Start discovery")
            self.discover()
            log.debug("Finish discovery")
            self.writejson()
            sleep(60)

def main():
    """Main function for running class directly"""
    swarmer = PrometheusSwarmer()
    swarmer.run()

if __name__ == '__main__':
    main()
