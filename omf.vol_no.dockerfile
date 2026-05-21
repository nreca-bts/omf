# A Dockerfile for running the Open Modeling Framework
FROM ubuntu:24.04
LABEL maintainer=<david.pinney@nreca.coop>

# Install the OMF
RUN apt-get -y update && apt-get install -y git python3 sudo
RUN cd home; python3 -m pip install git+https://github.com/nreca-bts/omf

# Run the OMF
EXPOSE 5001
WORKDIR /home/omf/omf
ENTRYPOINT ["python3"]
CMD ["web.py"]

# INSTRUCTIONS
# ============
# - Navigate to this directory
# - Build image with command `docker build -f newomf.dockerfile -t omfim .`
# - Run image in background with `docker run -d -p 5001:5001 --name omfcon omfim`
# - View at http://127.0.0.1:5001
# - Stop it with `docker stop omfcon` and remove it with `docker rm omfcon`.
# - Delete the images with `docker rmi omfim`
# 
# FEATURE IDEAS
# =============
# - Python "build" script to create, start and exit the image
# - Modify Dockerfile to use a network drive containing the omf repo instead of doing a fresh git pull