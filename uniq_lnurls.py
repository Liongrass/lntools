from os import write
import requests
import csv
import json

'''
Be sure to set a proper x_api_key ID first.

from lnbits docs, see examples at: https://github.com/fiatjaf/awesome-lnurl
shareable link format example: https://lnbits.com/withdraw/hAoEFZtbrNctpL8VEPVQcD
Withdraw ID example: hAoEFZtbrNctpL8VEPVQcD
'''

x_api_key = ""
lnhost = "lnbits.com"
lnbase = "https://" + lnhost + "/withdraw"
lnurlw =  lnbase + "/api/v1/links"

##################################
# default variables
title = "testurl1"
min_with = 5000
max_with = 5000
uses = 1
wait_time = 1


params = {"title": title,
          "min_withdrawable": min_with,
          "max_withdrawable": max_with,
          "uses": uses,
          "wait_time": wait_time,
          "is_unique": False}

headers = {"X-Api-Key" : x_api_key,
           "Content-type" : "application/json"}


# list withdraw links
def list_link_data(headers):
    res = requests.get(lnurlw, headers=headers)
    datum = res.json()
    for i in datum:
        print(i['id'])

# get withdraw link
def get_link(id, headers):
    res = requests.get(lnurlw+"/"+id, headers=headers)
    link_data = res.json()
    lnurl = link_data['lnurl']
    print(link_data)
    print(lnurl)
    return lnurl

# delete a link
def del_link(id, headers):
    print(f"deleteing id: {id}")
    res = requests.delete(lnurlw+"/"+id, headers=headers)
    return res.text

# create a new link
def create_link(params, headers):
    try:
        res = requests.post(lnurlw, data=params, headers=headers)
        print("\t ==== creating link ====")
        rdata = res.json()
        return rdata
    except Exception as e:
        print("Exception thrown while trying to create link" + e)
        return


def write_csv(filename, data):
    fieldnames = ['title', 'sats', 'sharelink', 'lnurl']
    with open('csv/'+filename, mode='w') as csv_file:
        csv_writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        csv_writer.writeheader()
        for row in data:
            csv_writer.writerow(row)


def process_csv(infile, headers):
    try:
        output_links = []
        with open('csv/'+infile, mode='r') as csv_file:
            csv_reader = csv.DictReader(csv_file)
            line_count = 0
            for row in csv_reader:
                if line_count == 0:
                    print(f'Column names are {", ".join(row)}')
                    line_count += 1
                title = row["title"]
                maxsat = row["maxsat"]
                uses = row["uses"]
                print(f'\t Title: {title},  Max Satoshis: {maxsat}, Number Uses: {uses}')
                params = {"title": title,
                        "min_withdrawable": int(maxsat),
                        "max_withdrawable": int(maxsat),
                        "uses": int(uses),
                        "wait_time": wait_time,
                        "is_unique": True}
                sparams = json.dumps(params)
                rdata = create_link(sparams, headers)
                lnurl = rdata['lnurl']
                lnid = rdata['id']
                share_link = lnbase + "/" + lnid
                outdata = {}
                outdata['title'] = title
                outdata['sats'] = maxsat
                outdata['sharelink'] = share_link
                outdata['lnurl'] = lnurl
                output_links.append(outdata)
                line_count += 1
            print(f'Processed {line_count} lines.')
            return output_links
    except Exception as e:
        print("Exception thrown while trying to create link" + e)
        return


# test methods individually
def unit_tests():
    # test ID of the LNURLw
    sample_id = "hAoEFZtbrNctpL8VEPVQcD"
    x_api_key = "08f44a4395ee4bf1910960587db30a21"

    headers = {"X-Api-Key" : x_api_key,
            "Content-type" : "application/json"}

    list_link_data(headers)
    get_link(sample_id, headers)
    del_link(sample_id, headers)
    print("Creating new link")
    sparams = json.dumps(params)
    rdata = create_link(sparams, headers)
    lnurl = rdata['lnurl']
    print(f"LNURLw = {lnurl}")

    infile = './csv/laisee.csv'
    outfile = './csv/laisee_out.csv'
    data = process_csv(infile, headers)
    write_csv(outfile, data)



if __name__ == "__main__":

    lnhost = input('Hi - This is the Unique LNURLw generator. \nBe sure no extra spaces are entered below. \nPlease enter your LNbits host (e.g. lnbits.com): ')
    lnbase = "https://" + lnhost + "/withdraw"
    lnurlw =  lnbase + "/api/v1/links"

    x_api_key = input('Please Enter your x-api-key: ')

    infile = input('Enter your .csv file name: ')
    outfile = input('Enter your output file name: ')
    headers = {"X-Api-Key" : x_api_key,
               "Content-type" : "application/json"}

    print("Okay, Processing.........")
    data = process_csv(infile, headers)
    write_csv(outfile, data)
    print(f" >>>>>>>>> Finished writing out to {outfile}\n\n")
