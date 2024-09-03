#!/bin/env python3

import argparse
import yaml

parser=argparse.ArgumentParser(description="Filter OLM file based index")
parser.add_argument("-o","--out", help="Output file", required=True)
parser.add_argument("-v","--verbose", action="store_true", help="Be more verbose", required=False)
parser.add_argument("-c","--config", help="yaml config file, pre-sets how packages are handled", required=False)
parser.add_argument("infile", help="Input index file")
try:
    args = parser.parse_args()
except Exception as e:
    parser.print_help()
    raise e

packageChoices={}
defaultPackageChoice=None
if args.config is not None:
    try:
        with open(args.config) as cfg:
            config = yaml.safe_load(cfg)
            for key,value in config.items():
                if "default" == key:
                    defaultPackageChoice = value
                else:
                    packageChoices[key] = value
    except Exception as e:
        print("Bad config file")
        raise e

def handleCurrent(currentYaml):
    global packageChoices
    single = "\n".join(currentYaml)
    yamlDict = None
    try:
        yamlDict = yaml.safe_load(single)
    except:
        print("Failed to load as yaml")
    if yamlDict is None:
        print("Failed to parse")
        return

    schema=yamlDict.get("schema","-")
    name=yamlDict.get("name","-")
    package=yamlDict.get("package","-")
    print("%s %s %s"%(schema, package, name))
    if "olm.package" == schema:
        # Ensure the entry exists, setting the default if needed and
        # asking the user if there is no config value or default.
        if packageChoices.setdefault(name, defaultPackageChoice) is None:
            choice=input("Keep [a]ll, [n]one or [x]ask from package %s[a|n|x]? "%(name))
            if "a" == choice:
                packageChoices[name] = "all"
            elif "n" == choice:
                packageChoices[name] = "none"
            else:
                packageChoices[name] = "ask"
                # For the logic below we use the package. For olm.package the
                # package is empty but name is the package.
        package = name
    packageSetting=packageChoices.get(package, "ask")
    if "all" == packageSetting:
        if args.verbose:
            print("  Keeping based on package choice")
        choice = "y"
    elif "none" == packageSetting:
        if args.verbose:
            print("  SKIPPING based on package choice")
        choice = "n"
    else:
        choice=input("Keep this piece[y|n]? ")
    if 0 == len(choice):
        choice="n"
    if "y" == choice:
        if args.verbose:
            print("  saving...")
        with open(args.out,"a") as out:
            out.write(single)
            out.write("\n")

with open(args.infile) as yfile:
    currentYaml=[]
    for line in yfile:
        line = line.rstrip()
        if line == "---":
            handleCurrent(currentYaml)
            currentYaml=[]
        else:
            pass
        currentYaml.append(line)
    # Handle the trailing lines
    handleCurrent(currentYaml)