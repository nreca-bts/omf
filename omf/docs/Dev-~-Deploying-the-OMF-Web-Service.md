Please note that these instructions in this document refer to hosts and directories that are specific to omf.coop.

### Dev Deployment 

See the [Developer Documentation](./Dev-~-Installation-Instructions).

### Prod Deployment

1. Bring up an Ubuntu 18.04 LTS machine.
2. Complete the [developer installation](./Dev-~-Installation-Instructions) production server.
3. Enable the service by `cp /omf/omf.service /etc/systemd/system/omf.service`.
4. Make sure we're starting on boot via `sudo systemctl enable omf`.
5. Add the SSL certificates to /omf/omf/omfDevCert.pem, /omf/omf/omfDevKey.pem, and /omf/omf/certChain.ca-bundle (ask David for it).
6. Add the emailCredentials.key to /omf/omf/ (ask David for it).
7. Start the service by running `systemctl start omf`.
8. Updates to prod can be done by running the cloudDeploy.sh script.

### SSL Certificate Generation

1. Create a key pair with `openssl genrsa -des3 -out sslCert_KEY.pem 4096`
2. CSR request creation with `openssl req -new -key .\sslCert_KEY.pem -out sslCert_CSR.pem`
3. Upload CSR text to the CA. We use Thawte via thesslstore.com. Do their email verification. Download completed cert as sslCert_CERT.cert and chain of vertification as sslCert_CHAIN.pem.
4. Translate cert to pem format: `openssl x509 -in sslCert_CERT.crt -out sslCert_CERT.der -outform DER; openssl x509 -in sslCert_CERT.der -inform DER -out sslCert_CERT.pem -outform PEM`.
5. Put on server as described above.

If you are testing SSL on a test instance, you can generate self-signed keys via the instructions in webProd.py.

### Backup

We use [AWS backup](https://aws.amazon.com/backup/) to store weekly snapshots of the production instance.

Restoration process:
1. Create a volume from the EBS snapshot. Make sure it's in the same region as the EC2 instance you will attach it to.
2. Attach the volume to an instance. Choose (e.g.) /dev/xvdb as the device ID.
3. SSH in to the instance you attached it to, and as root do (e.g.) `mkdir /backup; mount /dev/xvdb1 /backup`. The 1 indicates first partition.
4. When you're done, `umount /dev/xvdb1`