#!/bin/bash

SCRIPT_DIRECTORY="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

mkdir -p ${SCRIPT_DIRECTORY}/20130502/sifting ${SCRIPT_DIRECTORY}/populations

wget -O ${SCRIPT_DIRECTORY}/20130502/columns.txt \
        https://raw.githubusercontent.com/pegasus-isi/1000genome-workflow/master/data/20130502/columns.txt

for i in {1..8}; do
  wget -O ${SCRIPT_DIRECTORY}/20130502/ALL.chr${i}.250000.vcf.gz \
          https://github.com/pegasus-isi/1000genome-workflow/raw/master/data/20130502/ALL.chr${i}.250000.vcf.gz
  wget -O ${SCRIPT_DIRECTORY}/20130502/sifting/ALL.chr${i}.phase3_shapeit2_mvncall_integrated_v5.20130502.sites.annotation.vcf.gz \
          ftp://ftp.1000genomes.ebi.ac.uk/vol1/ftp/release/20130502/supporting/functional_annotation/filtered/ALL.chr${i}.phase3_shapeit2_mvncall_integrated_v5.20130502.sites.annotation.vcf.gz
done

populations=('AFR' 'ALL' 'AMR' 'EAS' 'EUR' 'GBR' 'SAS')
for p in ${populations[*]}; do
  wget -O ${SCRIPT_DIRECTORY}/populations/${p} \
          https://raw.githubusercontent.com/pegasus-isi/1000genome-workflow/master/data/populations/${p}
done
