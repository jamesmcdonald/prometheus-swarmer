# prometheus-swarmer

Discover services running in a Docker swarm (swarm mode) and generate
Prometheus JSON configuration to scrape them.

By default, `prometheus-swarmer` will look for a swarm service named
'prometheus' and get a list of the networks that service runs on. If it
can't find such a service, it defaults to looking for a network called
'proxy'.

It will then scan all the services in the swarm. To configure the port
number to scrape, you can either create a service label
`prometheus.port` or an environment variable called `SERVICE_PORTS`,
which are looked for in that order. The `SERVICE_PORTS` variable may be
a comma-separated list, in which case the first number will be used.
This arrangement allows for compatiblility with
[dockercloud/haproxy](https://github.com/docker/dockercloud-haproxy).

If a port is found and the service is on one of the list of networks
discovered above, an endpoint configuration is generated. The list of
endpoints is output as a json file. The default path for this is
`/etc/prometheus/swarm.d/service.json`.

## Caveats

This requires running prometheus and prometheus-swarmer to the same
node to be able to share a volume. Docker swarm doesn't provide a
mechanism for sidecar containers like Kubernetes's pods, so it is
necessary to bind both services to the same host with constraints.

## Quickstart

Create a prometheus config file, something like:

    ---
    global:
      scrape_interval:     15s
      evaluation_interval: 15s
    
    scrape_configs:
      - job_name: prometheus
        static_configs:
          - targets:
            - 127.0.0.1:9090
    
      - job_name: service_sd
        file_sd_configs:
          - files:
            - /etc/prometheus/swarm.d/*.json

Start the prometheus service:

    docker service create --name prometheus --constraint node.hostname==promnode \
        --mount source=/storage/prometheus,target=/prometheus,type=bind \
        --mount source=/config/prometheus.yml,target=/etc/prometheus/prometheus.yml,type=bind \
        --mount source=prometheus-swarm,target=/etc/prometheus/swarm.d \
		prom/prometheus

Here I have an extra volume bind-mounted on /prometheus to persist Prometheus's
own data.

Build prometheus-swarmer:

    docker build -t prometheus-swarmer .

Optionally push it to your registry like any other image.

Start prometheus-swarmer:

    docker service create --name prometheus-swarmer --constraint node.hostname==promnode \
        --mount source=/var/run/docker.sock,target=/var/run/docker.sock,type=bind \
		--mount source=prometheus-swarm,target=/etc/prometheus/swarm.d \
		prometheus-swarmer
