#!/bin/bash
# Open Omniscience Desktop Launcher Installer
# This script copies the desktop launcher to the user's desktop

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
APP_NAME="open-omniscience"
DESKTOP_FILE="open-omniscience-user.desktop"
ICON_FILE="open-omniscience.png"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SOURCE_DIR")"

# Function to get user's desktop directory
get_desktop_dir() {
    # Try XDG_DESKTOP_DIR first
    if [ -n "$XDG_DESKTOP_DIR" ] && [ -d "$XDG_DESKTOP_DIR" ]; then
        echo "$XDG_DESKTOP_DIR"
        return 0
    fi
    
    # Try common desktop directories
    local desktop_dirs=(
        "$HOME/Desktop"
        "$HOME/desktop"
        "$HOME/Desktop"
        "$HOME/Bureau"  # French
        "$HOME/Schreibtisch"  # German
        "$HOME/Escritorio"  # Spanish
        "$HOME/Desktop"
    )
    
    for dir in "${desktop_dirs[@]}"; do
        if [ -d "$dir" ]; then
            echo "$dir"
            return 0
        fi
    done
    
    # Fallback: create Desktop directory
    mkdir -p "$HOME/Desktop"
    echo "$HOME/Desktop"
}

# Function to get user's local applications directory
get_local_apps_dir() {
    if [ -n "$XDG_DATA_HOME" ]; then
        echo "$XDG_DATA_HOME/applications"
    else
        echo "$HOME/.local/share/applications"
    fi
}

# Function to get user's local icons directory
get_local_icons_dir() {
    if [ -n "$XDG_DATA_HOME" ]; then
        echo "$XDG_DATA_HOME/icons"
    else
        echo "$HOME/.local/share/icons"
    fi
}

# Function to install desktop file
install_desktop_file() {
    local desktop_dir
    local apps_dir
    local icons_dir
    
    desktop_dir=$(get_desktop_dir)
    apps_dir=$(get_local_apps_dir)
    icons_dir=$(get_local_icons_dir)
    
    echo -e "${BLUE}Installing Open Omniscience desktop launcher...${NC}"
    echo ""
    
    # Create directories if they don't exist
    mkdir -p "$desktop_dir"
    mkdir -p "$apps_dir"
    mkdir -p "$icons_dir"
    
    # Copy desktop file to user's desktop
    echo -e "${GREEN}Copying desktop file to: $desktop_dir/${DESKTOP_FILE}${NC}"
    cp "$SOURCE_DIR/$DESKTOP_FILE" "$desktop_dir/$DESKTOP_FILE"
    chmod +x "$desktop_dir/$DESKTOP_FILE"
    
    # Copy desktop file to local applications (for menu)
    echo -e "${GREEN}Copying desktop file to: $apps_dir/${DESKTOP_FILE}${NC}"
    cp "$SOURCE_DIR/$DESKTOP_FILE" "$apps_dir/$DESKTOP_FILE"
    chmod +x "$apps_dir/$DESKTOP_FILE"
    
    # Update the desktop file paths to use local icon
    local local_icon_path="$icons_dir/$ICON_FILE"
    
    # Create local icon directory
    mkdir -p "$icons_dir"
    
    # Copy icon to local icons directory
    if [ -f "$PROJECT_ROOT/package/deb/open-omniscience.svg" ]; then
        echo -e "${GREEN}Copying icon to: $local_icon_path${NC}"
        # Try to convert SVG to PNG if ImageMagick is available
        if command -v convert &> /dev/null; then
            convert -background none -resize 256x256 \
                "$PROJECT_ROOT/package/deb/open-omniscience.svg" \
                "$local_icon_path"
        else
            # Fallback: copy SVG as PNG (will use SVG directly)
            cp "$PROJECT_ROOT/package/deb/open-omniscience.svg" "$local_icon_path"
        fi
    elif [ -f "$PROJECT_ROOT/package/deb/open-omniscience.png" ]; then
        echo -e "${GREEN}Copying icon to: $local_icon_path${NC}"
        cp "$PROJECT_ROOT/package/deb/open-omniscience.png" "$local_icon_path"
    fi
    
    # Update desktop files to use local icon path
    if [ -f "$local_icon_path" ]; then
        echo -e "${GREEN}Updating desktop files to use local icon...${NC}"
        sed -i "s|Icon=/usr/share/pixmaps/open-omniscience.png|Icon=$local_icon_path|" \
            "$desktop_dir/$DESKTOP_FILE"
        sed -i "s|Icon=/usr/share/pixmaps/open-omniscience.png|Icon=$local_icon_path|" \
            "$apps_dir/$DESKTOP_FILE"
    fi
    
    # Make desktop files executable
    chmod +x "$desktop_dir/$DESKTOP_FILE"
    chmod +x "$apps_dir/$DESKTOP_FILE"
    
    echo ""
    echo -e "${GREEN}Desktop launcher installed successfully!${NC}"
    echo ""
    echo "Launcher locations:"
    echo "  - Desktop: $desktop_dir/$DESKTOP_FILE"
    echo "  - Applications menu: $apps_dir/$DESKTOP_FILE"
    echo "  - Icon: $local_icon_path"
    echo ""
}

# Function to uninstall desktop file
uninstall_desktop_file() {
    local desktop_dir
    local apps_dir
    local icons_dir
    
    desktop_dir=$(get_desktop_dir)
    apps_dir=$(get_local_apps_dir)
    icons_dir=$(get_local_icons_dir)
    
    echo -e "${YELLOW}Uninstalling Open Omniscience desktop launcher...${NC}"
    echo ""
    
    # Remove desktop file from desktop
    if [ -f "$desktop_dir/$DESKTOP_FILE" ]; then
        echo -e "${GREEN}Removing: $desktop_dir/$DESKTOP_FILE${NC}"
        rm -f "$desktop_dir/$DESKTOP_FILE"
    fi
    
    # Remove desktop file from applications
    if [ -f "$apps_dir/$DESKTOP_FILE" ]; then
        echo -e "${GREEN}Removing: $apps_dir/$DESKTOP_FILE${NC}"
        rm -f "$apps_dir/$DESKTOP_FILE"
    fi
    
    # Remove icon
    if [ -f "$icons_dir/$ICON_FILE" ]; then
        echo -e "${GREEN}Removing: $icons_dir/$ICON_FILE${NC}"
        rm -f "$icons_dir/$ICON_FILE"
    fi
    
    echo ""
    echo -e "${GREEN}Desktop launcher uninstalled successfully!${NC}"
    echo ""
}

# Function to check if desktop launcher is installed
check_installation() {
    local desktop_dir
    local apps_dir
    
    desktop_dir=$(get_desktop_dir)
    apps_dir=$(get_local_apps_dir)
    
    echo -e "${BLUE}Checking Open Omniscience desktop launcher installation...${NC}"
    echo ""
    
    if [ -f "$desktop_dir/$DESKTOP_FILE" ]; then
        echo -e "${GREEN}✓ Desktop launcher found on desktop: $desktop_dir/$DESKTOP_FILE${NC}"
    else
        echo -e "${RED}✗ Desktop launcher NOT found on desktop${NC}"
    fi
    
    if [ -f "$apps_dir/$DESKTOP_FILE" ]; then
        echo -e "${GREEN}✓ Desktop launcher found in applications: $apps_dir/$DESKTOP_FILE${NC}"
    else
        echo -e "${RED}✗ Desktop launcher NOT found in applications${NC}"
    fi
    
    echo ""
}

# Main function
main() {
    echo "=========================================="
    echo "Open Omniscience Desktop Launcher Installer"
    echo "=========================================="
    echo ""
    
    case "${1:-help}" in
        install|--install|-i)
            install_desktop_file
            ;;
        uninstall|--uninstall|-u)
            uninstall_desktop_file
            ;;
        check|--check|-c)
            check_installation
            ;;
        help|--help|-h|*)
            echo "Usage: $0 [COMMAND]"
            echo ""
            echo "Commands:"
            echo "  install    - Install desktop launcher to user's desktop"
            echo "  uninstall  - Remove desktop launcher from user's desktop"
            echo "  check      - Check if desktop launcher is installed"
            echo "  help       - Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 install"
            echo "  $0 uninstall"
            echo "  $0 check"
            echo ""
            ;;
    esac
}

# Run main function
main "$@"
