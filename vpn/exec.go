package main

import "syscall"

// execv replaces this process, so `vpn run` becomes the app itself.
func execv(path string, args []string) error {
	return syscall.Exec(path, args, syscall.Environ())
}
