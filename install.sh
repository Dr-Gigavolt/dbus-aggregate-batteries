#!/bin/bash

# remove comment for easier troubleshooting
#set -x

# this file has also to work for older driver versions
# else it won't work to install an older version


# check if /data/apps path exists
if [ ! -d "/data/apps" ]; then
    mkdir -p /data/apps
fi



function backup_config {
    # backup config.ini
    # driver >= v4.0.0
    if [ -f "/data/apps/dbus-aggregate-batteries/config.ini" ]; then
        mv /data/apps/dbus-aggregate-batteries/config.ini /data/apps/dbus-aggregate-batteries_config.ini.backup
        echo "config.ini backed up to /data/apps/dbus-aggregate-batteries_config.ini.backup"
    # driver < v4.0.0
    elif [ -f "/data/dbus-aggregate-batteries/settings.py" ]; then
        mv /data/dbus-aggregate-batteries/settings.py /data/dbus-aggregate-batteries_settings.py.backup
        echo "settings.py backed up to /data/dbus-aggregate-batteries_settings.py.backup"
    fi

    # backup storedvalue_charge
    # driver >= v4.0.0
    if [ -f "/data/apps/dbus-aggregate-batteries/storedvalue_charge" ]; then
        mv /data/apps/dbus-aggregate-batteries/storedvalue_charge /data/apps/dbus-aggregate-batteries_storedvalue_charge.backup
        echo "storedvalue_charge backed up to /data/apps/dbus-aggregate-batteries_storedvalue_charge.backup"
    # driver < v4.0.0
    elif [ -f "/data/dbus-aggregate-batteries/charge" ]; then
        mv /data/dbus-aggregate-batteries/charge /data/dbus-aggregate-batteries_charge.backup
        echo "charge backed up to /data/dbus-aggregate-batteries_charge.backup"
    fi

    # backup storedvalue_last_balancing
    # driver >= v4.0.0
    if [ -f "/data/apps/dbus-aggregate-batteries/storedvalue_last_balancing" ]; then
        mv /data/apps/dbus-aggregate-batteries/storedvalue_last_balancing /data/apps/dbus-aggregate-batteries_storedvalue_last_balancing.backup
        echo "storedvalue_last_balancing backed up to /data/apps/dbus-aggregate-batteries_storedvalue_last_balancing.backup"
    # driver < v4.0.0
    elif [ -f "/data/dbus-aggregate-batteries/last_balancing" ]; then
        mv /data/dbus-aggregate-batteries/last_balancing /data/dbus-aggregate-batteries_last_balancing.backup
        echo "last_balancing backed up to /data/dbus-aggregate-batteries_last_balancing.backup"
    fi
}

function restore_config {
    # restore config.ini
    # installation of driver >= v4.0.0
    if [ -f "/data/apps/dbus-aggregate-batteries_config.ini.backup" ]; then
        # restore to driver >= v4.0.0 (normal update)
        if [ -d "/data/apps/dbus-aggregate-batteries" ]; then
            mv /data/apps/dbus-aggregate-batteries_config.ini.backup /data/apps/dbus-aggregate-batteries/config.ini
            echo "config.ini restored to /data/apps/dbus-aggregate-batteries/config.ini"
        # restore to driver < v4.0.0 (downgrade)
        elif [ -d "/data/dbus-aggregate-batteries" ]; then
            mv /data/apps/dbus-aggregate-batteries_config.ini.backup /data/dbus-aggregate-batteries/config.ini
            # print in red color
            echo -e "\e[31m"
            echo "WARNING: downgrade detected, configurations not compatible!"
            echo "         config.ini NOT restored to /data/dbus-aggregate-batteries/config.ini"
            echo "         Please reconfigure the old settings.py manually!"
            echo "         The new config.ini is available at /data/apps/dbus-aggregate-batteries_config.ini.backup"
            echo -e "\e[0m"
        fi
    # installation of driver < v4.0.0
    elif [ -f "/data/dbus-aggregate-batteries_settings.py.backup" ]; then
        # restore to driver >= v4.0.0 (upgrade)
        if [ -d "/data/apps/dbus-aggregate-batteries" ]; then
            # print in red color
            echo -e "\e[31m"
            echo "WARNING: upgrade detected, configurations not compatible!"
            echo "         settings.py NOT restored to /data/apps/dbus-aggregate-batteries/settings.py"
            echo "         Please reconfigure the new config.ini manually!"
            echo "         The old settings.py is available at /data/dbus-aggregate-batteries_settings.py.backup"
            echo -e "\e[0m"
        # restore to driver < v4.0.0 (normal update)
        elif [ -d "/data/dbus-aggregate-batteries" ]; then
            mv /data/dbus-aggregate-batteries_settings.py.backup /data/dbus-aggregate-batteries/settings.py
            echo "settings.py restored to /data/dbus-aggregate-batteries/settings.py"
        fi
    fi

    # restore storedvalue_charge
    # installation of driver >= v4.0.0
    if [ -f "/data/apps/dbus-aggregate-batteries_storedvalue_charge.backup" ]; then
        # restore to driver >= v4.0.0 (normal update)
        if [ -d "/data/apps/dbus-aggregate-batteries" ]; then
            mv /data/apps/dbus-aggregate-batteries_storedvalue_charge.backup /data/apps/dbus-aggregate-batteries/storedvalue_charge
            echo "storedvalue_charge restored to /data/apps/dbus-aggregate-batteries/storedvalue_charge"
        # restore to driver < v4.0.0 (downgrade)
        elif [ -d "/data/dbus-aggregate-batteries" ]; then
            mv /data/apps/dbus-aggregate-batteries_storedvalue_charge.backup /data/dbus-aggregate-batteries/charge
            echo "storedvalue_charge restored to /data/dbus-aggregate-batteries/charge"
        fi
    # installation of driver < v4.0.0
    elif [ -f "/data/dbus-aggregate-batteries_charge.backup" ]; then
        # restore to driver >= v4.0.0 (upgrade)
        if [ -d "/data/apps/dbus-aggregate-batteries" ]; then
            mv /data/dbus-aggregate-batteries_charge.backup /data/apps/dbus-aggregate-batteries/storedvalue_charge
            echo "charge restored to /data/apps/dbus-aggregate-batteries/storedvalue_charge"
        # restore to driver < v4.0.0 (normal update)
        elif [ -d "/data/dbus-aggregate-batteries" ]; then
            mv /data/dbus-aggregate-batteries_charge.backup /data/dbus-aggregate-batteries/charge
            echo "charge restored to /data/dbus-aggregate-batteries/charge"
        fi
    fi

    # restore storedvalue_last_balancing
    # installation of driver >= v4.0.0
    if [ -f "/data/apps/dbus-aggregate-batteries_storedvalue_last_balancing.backup" ]; then
        # restore to driver >= v4.0.0 (normal update)
        if [ -d "/data/apps/dbus-aggregate-batteries" ]; then
            mv /data/apps/dbus-aggregate-batteries_storedvalue_last_balancing.backup /data/apps/dbus-aggregate-batteries/storedvalue_last_balancing
            echo "storedvalue_last_balancing restored to /data/apps/dbus-aggregate-batteries/storedvalue_last_balancing"
        # restore to driver < v4.0.0 (downgrade)
        elif [ -d "/data/dbus-aggregate-batteries" ]; then
            mv /data/apps/dbus-aggregate-batteries_storedvalue_last_balancing.backup /data/dbus-aggregate-batteries/last_balancing
            echo "storedvalue_last_balancing restored to /data/dbus-aggregate-batteries/last_balancing"
        fi
    # installation of driver < v4.0.0
    elif [ -f "/data/dbus-aggregate-batteries_last_balancing.backup" ]; then
        # restore to driver >= v4.0.0 (upgrade)
        if [ -d "/data/apps/dbus-aggregate-batteries" ]; then
            mv /data/dbus-aggregate-batteries_last_balancing.backup /data/apps/dbus-aggregate-batteries/storedvalue_last_balancing
            echo "last_balancing restored to /data/apps/dbus-aggregate-batteries/storedvalue_last_balancing"
        # restore to driver < v4.0.0 (normal update)
        elif [ -d "/data/dbus-aggregate-batteries" ]; then
            mv /data/dbus-aggregate-batteries_last_balancing.backup /data/dbus-aggregate-batteries/last_balancing
            echo "last_balancing restored to /data/dbus-aggregate-batteries/last_balancing"
        fi
    fi
}



echo
echo "*** Welcome to the dbus-aggregate-batteries installer! ***"
echo



# check command line arguments
if [ -z "$1" ]; then

    # fetch version numbers for different versions
    echo -n "Fetch available version numbers..."

    # stable
    latest_release_stable=$(curl -s https://api.github.com/repos/Dr-Gigavolt/dbus-aggregate-batteries/releases/latest | sed -nE 's/.*"tag_name": "([^"]+)".*/\1/p')

    # beta
    latest_release_beta=$(curl -s https://api.github.com/repos/Dr-Gigavolt/dbus-aggregate-batteries/releases | sed -nE 's/.*"tag_name": "([^"]+(rc|beta))".*/\1/p' | head -n 1)

    # main branch
    latest_release_nightly=$(curl -s https://raw.githubusercontent.com/Dr-Gigavolt/dbus-aggregate-batteries/refs/heads/main/dbus-aggregate-batteries.py | grep "VERSION =" | awk -F'"' '{print "v" $2}')

    # done
    echo " done."

    # show current installed version
    # driver >= v4.0.0
    if [ -f "/data/apps/dbus-aggregate-batteries/dbus-aggregate-batteries.py" ]; then
        current_version=$(grep "VERSION =" /data/apps/dbus-aggregate-batteries/dbus-aggregate-batteries.py | awk -F'"' '{print $2}')
        echo
        echo "** Currently installed version: v$current_version **"
    # driver < v4.0.0
    elif [ -f "/data/dbus-aggregate-batteries/dbus-aggregate-batteries.py" ]; then
        current_version=$(grep "VERSION =" /data/dbus-aggregate-batteries/dbus-aggregate-batteries.py | awk -F'"' '{print $2}')
        echo
        echo "** Currently installed version: v$current_version **"
    fi

###########################

    echo
    PS3=$'\nSelect which version you want to install and enter the corresponding number: '

    # create list of versions
    version_list=(
        "stable release \"$latest_release_stable\""
        "beta build \"$latest_release_beta\""
        "nightly build \"$latest_release_nightly\""
        "specific branch (specific feature testing)"
        "specific version"
        "local zip file"
        "quit"
    )

    select version in "${version_list[@]}"
    do
        case $version in
            "stable release \"$latest_release_stable\"")
                break
                ;;
            "beta build \"$latest_release_beta\"")
                break
                ;;
            "nightly build \"$latest_release_nightly\"")
                break
                ;;
            "specific branch (specific feature testing)")
                break
                ;;
            "specific version")
                break
                ;;
            "local zip file")
                break
                ;;
            "quit")
                exit 0
                ;;
            *)
                echo "> Invalid option: $REPLY. Please enter a number!"
                ;;
        esac
    done

    echo "> Selected: $version"
    echo ""

    if [ "$version" = "stable release \"$latest_release_stable\"" ]; then
        version="stable"
    elif [ "$version" = "beta build \"$latest_release_beta\"" ]; then
        version="beta"
    elif [ "$version" = "nightly build \"$latest_release_nightly\"" ]; then
        version="nightly"
    elif [ "$version" = "specific branch (specific feature testing)" ]; then
        version="specific_branch"
    elif [ "$version" = "specific version" ]; then
        version="specific_version"
    elif [ "$version" = "local zip file" ]; then
        version="local"
    fi

elif [ "$1" = "--stable" ]; then
    version="stable"

elif [ "$1" = "--beta" ]; then
    version="beta"

elif [ "$1" = "--nightly" ]; then
    version="nightly"

elif [ "$1" = "--local" ]; then
    version="local"

else
    echo
    echo "No valid command line argument given. Possible arguments are:"
    echo "  --latest   Install the latest stable release"
    echo "  --beta     Install the latest beta release"
    echo "  --nightly  Install the latest nightly build"
    echo "  --local    Install a local zip file from \"/tmp/dbus-aggregate-batteries.zip\""
    echo
    exit 1
fi



## stable release (mr-manuel, most up to date)
if [ "$version" = "stable" ]; then
    # download stable release
    echo "Downloading stable release..."
    echo ""
    curl -s https://api.github.com/repos/Dr-Gigavolt/dbus-aggregate-batteries/releases/latest | sed -nE 's/.*"zipball_url": "([^"]+)".*/\1/p' | wget -O /tmp/dbus-aggregate-batteries.zip -i -
    # check if the download was successful
    if [ $? -ne 0 ]; then
        echo "ERROR: Error during downloading the ZIP file. Please try again."
        exit 1
    fi
    echo ""
fi

## beta release (mr-manuel, most up to date)
if [ "$version" = "beta" ]; then
    # download beta release
    echo "Downloading beta release..."
    echo ""
    curl -s https://api.github.com/repos/Dr-Gigavolt/dbus-aggregate-batteries/releases/tags/$latest_release_beta | sed -nE 's/.*"zipball_url": "([^"]+)".*/\1/p' | wget -O /tmp/dbus-aggregate-batteries.zip -i -
    # check if the download was successful
    if [ $? -ne 0 ]; then
        echo "ERROR: Error during downloading the ZIP file. Please try again."
        exit 1
    fi
    echo ""
fi

## specific version
if [ "$version" = "specific_version" ]; then
    # read the url
    read -r -p "Enter the url of the \"Source code (zip)\" you want to install: " zipball_url
    echo ""
    echo "Downloading specific version from $zipball_url..."
    echo ""
    wget -O /tmp/dbus-aggregate-batteries.zip "$zipball_url"
    if [ $? -ne 0 ]; then
        echo "ERROR: Error during downloading the ZIP file. Please check, if the URL is correct."
        exit 1
    fi
    echo ""
fi

## local zip file
if [ "$version" = "local" ]; then
    echo "Make sure the file is available at \"/tmp/dbus-aggregate-batteries.zip\"."
    echo
fi


## nightly builds
if [ "$version" = "nightly" ] || [ "$version" = "specific_branch" ]; then

    # ask which branch to install
    if [ "$version" = "specific_branch" ]; then

        # fetch branches from Github
        branches=$(curl -s https://api.github.com/repos/Dr-Gigavolt/dbus-aggregate-batteries/branches | sed -nE 's/.*"name": "([^"]+)".*/\1/p')

        # create a select menu
        echo
        PS3=$'\nSelect the branch you want to install and enter the corresponding number: '

        select branch in $branches
        do
            if [[ -z "$branch" ]]; then
                echo "> Invalid selection. Please try again."
            else
                break
            fi
        done

        echo "> Selected branch: $branch"

    else

        branch="main"

    fi

    # download driver
    echo "Downloading branch \"$branch\"..."
    echo ""
    wget -O /tmp/dbus-aggregate-batteries.zip https://github.com/Dr-Gigavolt/dbus-aggregate-batteries/archive/refs/heads/$branch.zip
    # check if the download was successful
    if [ $? -ne 0 ]; then
        echo "ERROR: Error during downloading the ZIP file. Please try again."
        exit 1
    fi
    echo ""
fi



# backup settings.py
backup_config


# get the name of the folder in the zip file
if [ -z "$branch" ]; then
    zip_root_folder=$(unzip -l /tmp/dbus-aggregate-batteries.zip | awk '{print $4}' | grep -oE '^[^/]+/' | head -n 1 | sed 's:/$::')
fi

# extract archive
# driver >= v4.0.0
if unzip -l /tmp/dbus-aggregate-batteries.zip | awk '{print $4}' | grep -q "^${zip_root_folder}/"; then
    unzip -q /tmp/dbus-aggregate-batteries.zip "${zip_root_folder}/*" -d /tmp
else
    echo "ERROR: ZIP file does not contain expected data. Check the file and try again."
    # restore settings.py
    restore_config
    exit 1
fi

# check if the extraction was successful
if [ $? -ne 0 ]; then
    echo "ERROR: Error during extracting the ZIP file. Check the file and try again."
    # restore settings.py
    restore_config
    exit 1
fi

# rename extracted folder to a fixed name
mv /tmp/${zip_root_folder} /tmp/dbus-aggregate-batteries

# remove old driver
# driver >= v4.0.0
if [ -d "/data/apps/dbus-aggregate-batteries" ]; then
    rm -rf /data/apps/dbus-aggregate-batteries
fi
# driver < v4.0.0
if [ -d "/data/dbus-aggregate-batteries" ]; then
    rm -rf /data/dbus-aggregate-batteries
fi

# move driver to the correct location
# driver >= v4.0.0
if [ -d "/tmp/dbus-aggregate-batteries" ]; then
    mv /tmp/dbus-aggregate-batteries /data/apps
# driver < v4.0.0
elif [ -d "/tmp/dbus-aggregate-batteries" ]; then
    mv /tmp/dbus-aggregate-batteries /data
else
    echo "ERROR: Something went wrong during moving the files from the temporary ZIP location to the final location. Please try again."
    exit 1
fi

# cleanup
rm /tmp/dbus-aggregate-batteries.zip
if [ -d "/tmp/dbus-aggregate-batteries" ]; then
    rm -rf /tmp/dbus-aggregate-batteries
fi

# fix permissions, owner and group
if [ -d "/data/apps/dbus-aggregate-batteries" ]; then
    chmod +x /data/apps/dbus-aggregate-batteries/*.sh
    chmod +x /data/apps/dbus-aggregate-batteries/*.py
    chmod +x /data/apps/dbus-aggregate-batteries/service/run
    chmod +x /data/apps/dbus-aggregate-batteries/service/log/run

    chown -R root:root /data/apps/dbus-aggregate-batteries
elif [ -d "/data/dbus-aggregate-batteries" ]; then
    chmod +x /data/dbus-aggregate-batteries/*.sh
    chmod +x /data/dbus-aggregate-batteries/*.py
    chmod +x /data/dbus-aggregate-batteries/service/run
    chmod +x /data/dbus-aggregate-batteries/service/log/run

    chown -R root:root /data/dbus-aggregate-batteries
fi



# restore settings.py
restore_config



# run install script >= v4.0.0
if [ -f "/data/apps/dbus-aggregate-batteries/enable.sh" ]; then
    bash /data/apps/dbus-aggregate-batteries/enable.sh
# run install script >= v1.0.0 and < v4.0.0
elif [ -f "/data/dbus-aggregate-batteries/reinstall-local.sh" ]; then
    bash /data/dbus-aggregate-batteries/reinstall-local.sh
fi
