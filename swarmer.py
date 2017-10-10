import docker
import json
import logging
from time import sleep
from pprint import pformat

log = logging
logging.basicConfig(level=logging.DEBUG)

log.info("In A.D. 2101 prometheus-swarmer was beginning.")
client = docker.from_env()

# The path to output the configuration to
outputpath = '/etc/prometheus/swarm.d/swarm-endpoints.json'

# Label name for prometheus port config
label_name = 'prometheus.port'

# Environment variable for prometheus port config
# SERVICE_PORTS is compatible with dockercloud/haproxy
env_name = 'SERVICE_PORTS'

# Name of the prometheus service to look for
service_name = 'prometheus'

# Look for a network called 'proxy' by default
default_pcnetworks = ['proxy']

# Find which networks the prometheus service is on
try:
    pcnetworks = []
    ps = client.services.get(service_name)
    pt = ps.tasks()[0]
    for na in pt['NetworksAttachments']:
        pcnetworks.append(na['Network']['Spec']['Name'])
except docker.errors.NotFound:
    pcnetworks = default_pcnetworks

while True:
    log.debug("Start discovery")
    endpoints = []
    for service in client.services.list():
        name = service.attrs['Spec']['Name']

        # Don't monitor prometheus itself (it can do that)
        if name == service_name:
            continue

        # Service labels
        slabels = service.attrs['Spec']['Labels']

        cs = service.attrs['Spec']['TaskTemplate']['ContainerSpec']

        # Container labels
        clabels = {}
        if 'Labels' in cs:
            clabels = cs['Labels']

        envs = []
        if 'Env' in cs:
            envs = cs['Env']

        port = None
        if label_name in slabels:
            port = slabels[label_name]
        else:
            ports = [x.split('=')[1] for x in envs if x.startswith(env_name + '=')]
            if len(ports) == 1:
                # Support a comma-separated list - take the first
                port = ports[0].split(',')[0]
        if port is None:
            log.debug("Unable to find port for service '{}', skipping".format(name))
            continue

        for task in service.tasks():
            # Skip tasks for containers that the service manager doesn't run anymore
            if task['DesiredState'] != 'running':
                continue

            # Add an endpoint for the first matching network
            if 'NetworksAttachments' not in task:
                log.debug("No network attachments for service '{}', skipping".format(name))
                continue
            for network in task['NetworksAttachments']:
                if network['Network']['Spec']['Name'] in pcnetworks:
                    address = network['Addresses'][0].split('/')[0]
                    endpoint = {
                        'targets': [address + ':' + port],
                        'labels': {
                            'job': name
                        }
                    }
                    for label in slabels:
                        l = label.replace('.', '_')
                        endpoint['labels']['service_label_{}'.format(l)] = slabels[label]
                    for label in clabels:
                        l = label.replace('.', '_')
                        endpoint['labels']['container_label_{}'.format(l)] = clabels[label]
                    endpoint['labels']['container_id'] = \
                        task['Status']['ContainerStatus']['ContainerID']
                    endpoints.append(endpoint)
                    log.debug('Add endpoint for {} at {}:{}'.format(name, address, port))
                    break

    log.debug(pformat(endpoints))
    with open(outputpath, "w") as jsonfile:
        json.dump(endpoints, jsonfile)
    log.debug("Finish discovery")
    sleep(60)
