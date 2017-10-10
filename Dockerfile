FROM python:alpine
COPY requirements.txt /
RUN pip install -r requirements.txt
VOLUME /etc/prometheus/services.d
COPY swarmer.py /
CMD python swarmer.py
