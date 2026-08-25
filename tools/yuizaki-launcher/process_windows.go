//go:build windows

package main

import (
	"fmt"
	"os/exec"
	"syscall"
)

func configureChildProcess(cmd *exec.Cmd) {
	// Keep backend/MCP children out of the user's console while retaining a
	// process group that can be terminated by the supervisor.
	cmd.SysProcAttr = &syscall.SysProcAttr{
		CreationFlags: 0x08000000 | 0x00000200,
	}
}

func stopChildProcess(cmd *exec.Cmd) error {
	if cmd == nil || cmd.Process == nil {
		return nil
	}
	return exec.Command("taskkill", "/T", "/F", "/PID", fmt.Sprint(cmd.Process.Pid)).Run()
}

func stopPID(pid int) error {
	return exec.Command("taskkill", "/T", "/F", "/PID", fmt.Sprint(pid)).Run()
}
