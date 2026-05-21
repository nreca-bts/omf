# A Dockerfile for running the Open Modeling Framework
FROM ubuntu:24.04
LABEL maintainer=<david.pinney@nreca.coop>

# Install and setup OMF reqs
RUN apt-get -y update && apt-get install -y python3 sudo vim python3-pip python3-setuptools
RUN mkdir /home/omf
RUN mkdir /home/omf/omf

# Do the install from this folder and have it cached as an intermediate image.
COPY pyproject.toml /home/omf/
RUN cd /home/omf/; python3 -m pip install .

# Run the OMF
EXPOSE 5001
VOLUME ["/home/omf/omf/"]
WORKDIR /home/omf/omf/
ENTRYPOINT ["python3"]
CMD ["web.py"]

# INSTRUCTIONS
# ============
# - Navigate to this directory
# - Build image with command `docker build . -f Dockerfile -t omfim`
# - Run image in background with `docker run -d -p 5001:5001 -v "`pwd`/omf":/home/omf/omf/ --name omfcont omfim`
# - View at http://127.0.0.1:5001
# - Stop it with `docker stop omfcont` and remove it with `docker rm omfcont`.
# - Delete the images with `docker rmi omfim`
# - Note that the source is mounted via a volume, so changes in the local file system will be reflected in the image/container