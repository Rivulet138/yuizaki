//go:build windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

func installWindowsShortcut(install bool, root, executable string) error {
	desktop := filepath.Join(os.Getenv("USERPROFILE"), "Desktop", "Yuizaki.lnk")
	startMenu := filepath.Join(os.Getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs", "Yuizaki.lnk")
	paths := []string{desktop, startMenu}
	if !install {
		for _, path := range paths {
			_ = os.Remove(path)
		}
		fmt.Println("[OK] Yuizaki shortcuts removed")
		return nil
	}
	for _, shortcut := range paths {
		if err := os.MkdirAll(filepath.Dir(shortcut), 0o755); err != nil {
			return err
		}
		ps := "$ws=New-Object -ComObject WScript.Shell;" +
			"$s=$ws.CreateShortcut('" + powershellQuote(shortcut) + "');" +
			"$s.TargetPath='" + powershellQuote(executable) + "';" +
			"$s.WorkingDirectory='" + powershellQuote(root) + "';" +
			"$s.Arguments='start';$s.Save()"
		if err := exec.Command("powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps).Run(); err != nil {
			return fmt.Errorf("create shortcut %s: %w", shortcut, err)
		}
	}
	fmt.Println("[OK] Yuizaki shortcuts installed")
	return nil
}

func powershellQuote(value string) string {
	return strings.ReplaceAll(value, "'", "''")
}

func installLinuxDesktopEntry(_ bool, _, _ string) error {
	return fmt.Errorf("Linux desktop entry helper is unavailable on Windows")
}
