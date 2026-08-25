//go:build !windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

func installLinuxDesktopEntry(install bool, root, executable string) error {
	base := os.Getenv("XDG_DATA_HOME")
	if base == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return err
		}
		base = filepath.Join(home, ".local", "share")
	}
	entryPath := filepath.Join(base, "applications", "yuizaki.desktop")
	if !install {
		_ = os.Remove(entryPath)
		fmt.Println("[OK] Yuizaki desktop entry removed")
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(entryPath), 0o755); err != nil {
		return err
	}
	entry := "[Desktop Entry]\n" +
		"Type=Application\n" +
		"Name=Yuizaki\n" +
		"Comment=Local-first AI desktop companion\n" +
		"Terminal=false\n" +
		"Exec=\"" + executable + "\" start\n" +
		"Path=" + root + "\n" +
		"Categories=Utility;AudioVideo;\n" +
		"StartupWMClass=com.yuizaki.desktop\n" +
		"X-GNOME-UsesNotifications=true\n" +
		"X-KDE-StartupNotify=true\n"
	if err := os.WriteFile(entryPath, []byte(entry), 0o755); err != nil {
		return err
	}
	if update, updateErr := exec.LookPath("update-desktop-database"); updateErr == nil {
		_ = exec.Command(update, filepath.Dir(entryPath)).Run()
	}
	fmt.Println("[OK] Yuizaki desktop entry installed: " + entryPath)
	return nil
}

func installWindowsShortcut(_ bool, _, _ string) error {
	return fmt.Errorf("Windows shortcut helper is unavailable on Linux")
}
