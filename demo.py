# -*- coding:utf-8 -*-
import aiml as aiml
import programy
import os


def _aiml():
    alice_path = './resources/alice'
    os.chdir(alice_path)
    alice = aiml.Kernel()
    alice.learn('startup.xml')
    alice.respond('LOAD ALICE')
    while True:
        print(alice.respond(input("Enter your message >> ")))


if __name__ == '__main__':
    print(1)
    _aiml()
