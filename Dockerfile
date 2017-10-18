FROM python:alpine
COPY requirements.txt /
RUN pip install -r requirements.txt
VOLUME /etc/prometheus/swarm.d
COPY prometheus-swarmer.py /
CMD python prometheus-swarmer.py
